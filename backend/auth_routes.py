"""
OptiBus Auth Routes — DevSecOps v4.0
Endpoints de autenticación: login, refresh, register, forgot/reset password, me.
Separado de main.py para mantener modularidad.
"""

import hashlib
import logging
from datetime import UTC, datetime, timedelta
from secrets import token_urlsafe

import models
from auth_utils import (
    create_jwt_token,
    hash_password,
    require_admin,
    verify_api_key,
    verify_password,
)
from config import ACCESS_TOKEN_EXPIRE_MINUTES, API_KEY_ENABLED, BUS_ID_PATTERN
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("optibus-auth-routes")

router = APIRouter(prefix="/api/auth", tags=["auth"])


# ── Pydantic Models ──


def _validate_email(v: str) -> str:
    """Valida y sanitiza email."""
    v = v.strip().lower()
    if "@" not in v or len(v) > 255:
        raise ValueError("Email inválido")
    return v


class LoginRequest(BaseModel):
    email: str
    password: str

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        return _validate_email(v)


class RegisterDriverRequest(BaseModel):
    email: str
    password: str
    name: str
    bus_id: str = "Bus-1"
    company: str = ""
    role: str = "driver"

    @field_validator("email")
    @classmethod
    def validate_email(cls, v):
        return _validate_email(v)

    @field_validator("bus_id")
    @classmethod
    def validate_bus_id(cls, v):
        if not BUS_ID_PATTERN.match(v):
            raise ValueError("bus_id inválido")
        return v


class ForgotPasswordRequest(BaseModel):
    email: str


class ResetPasswordRequest(BaseModel):
    token: str
    new_password: str


class AdminResetPasswordRequest(BaseModel):
    driver_id: int
    new_password: str


# ── Endpoints ──


@router.get("/status")
async def auth_status():
    """Estado de la configuración de autenticación."""
    return {"api_key_enabled": API_KEY_ENABLED, "version": "0.5.0"}


@router.post("/login")
async def login(request: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Inicia sesión con email + password. Retorna access_token + refresh_token + perfil."""
    result = await db.execute(
        select(models.Driver).where(
            and_(
                models.Driver.email == request.email,
                models.Driver.is_active.is_(True),
            )
        )
    )
    driver = result.scalar_one_or_none()
    if not driver or not driver.password_hash:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )
    if not verify_password(request.password, driver.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Credenciales inválidas",
        )

    access_token = create_jwt_token(driver.id, driver.bus_id, driver.role, "access", cooperative_id=driver.cooperative_id)
    refresh_token = create_jwt_token(driver.id, driver.bus_id, driver.role, "refresh", cooperative_id=driver.cooperative_id)

    logger.info(
        f"Login exitoso: {driver.email} (role={driver.role}, bus={driver.bus_id})"
    )
    return {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "expires_in_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
        "driver": {
            "id": driver.id,
            "name": driver.name,
            "email": driver.email,
            "bus_id": driver.bus_id,
            "company": driver.company,
            "role": driver.role,
        },
    }


@router.post("/refresh")
async def refresh_token(
    _auth: dict = Depends(verify_api_key), db: AsyncSession = Depends(get_db)
):
    """Refresca el access_token usando un refresh_token válido."""
    payload = _auth
    if isinstance(payload, dict) and payload.get("type") == "refresh":
        driver_id = payload["sub"]
        result = await db.execute(
            select(models.Driver).where(models.Driver.id == driver_id)
        )
        driver = result.scalar_one_or_none()
        if not driver or not driver.is_active:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Conductor no encontrado o inactivo",
            )

        access_token = create_jwt_token(
            driver.id, driver.bus_id, driver.role, "access"
        )
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in_minutes": ACCESS_TOKEN_EXPIRE_MINUTES,
        }
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail="Se requiere refresh_token (no access_token)",
    )


@router.post("/register")
async def register_driver(
    request: RegisterDriverRequest,
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Admin registra un nuevo conductor. Requiere API Key o JWT admin."""
    require_admin(_auth)

    existing = await db.execute(
        select(models.Driver).where(models.Driver.email == request.email)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="El email ya está registrado",
        )

    # Solo admin vía API Key puede asignar rol admin a otros
    assigned_role = (
        request.role
        if _auth.get("auth_type") == "api_key" and request.role == "admin"
        else "driver"
    )

    driver = models.Driver(
        email=request.email,
        password_hash=hash_password(request.password),
        name=request.name,
        bus_id=request.bus_id,
        company=request.company,
        role=assigned_role,
    )
    db.add(driver)
    await db.commit()
    await db.refresh(driver)

    logger.info(
        f"Nuevo conductor registrado: {driver.email} (ID={driver.id}, bus={driver.bus_id})"
    )
    return {
        "status": "created",
        "driver": {
            "id": driver.id,
            "name": driver.name,
            "email": driver.email,
            "bus_id": driver.bus_id,
            "company": driver.company,
            "role": driver.role,
        },
    }


@router.post("/forgot-password")
async def forgot_password(
    request: ForgotPasswordRequest,
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """
    Solicita recuperación de contraseña.
    DevSecOps: Solo el admin autenticado puede ver el reset_token.
    """
    result = await db.execute(
        select(models.Driver).where(
            and_(
                models.Driver.email == request.email,
                models.Driver.is_active.is_(True),
            )
        )
    )
    driver = result.scalar_one_or_none()
    if not driver:
        # No revelar si el email existe (timing-safe)
        return {
            "status": "ok",
            "message": "Si el email está registrado, el administrador recibirá la solicitud de recuperación.",
        }

    reset_token = token_urlsafe(32)
    driver.reset_token = hashlib.sha256(reset_token.encode()).hexdigest()
    driver.reset_token_expires_at = datetime.now(UTC) + timedelta(hours=1)
    await db.commit()

    logger.info(
        f"Solicitud de recuperación: {driver.email} (token expira en 1h)"
    )

    # DevSecOps: SOLO el admin ve el reset_token
    is_admin = isinstance(_auth, dict) and _auth.get("role") == "admin"
    response = {
        "status": "ok",
        "message": (
            "Solicitud recibida. El administrador debe proporcionar el token de recuperación."
        ),
    }
    if is_admin:
        response["reset_token_admin"] = reset_token  # Solo admin ve el token

    return response


@router.post("/reset-password")
async def reset_password(
    request: ResetPasswordRequest, db: AsyncSession = Depends(get_db)
):
    """Completa la recuperación de contraseña con el reset_token (entregado por el admin)."""
    token_hash = hashlib.sha256(request.token.encode()).hexdigest()
    result = await db.execute(
        select(models.Driver).where(
            and_(
                models.Driver.reset_token == token_hash,
                models.Driver.reset_token_expires_at > datetime.now(UTC),
                models.Driver.is_active.is_(True),
            )
        )
    )
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Token inválido o expirado",
        )

    driver.password_hash = hash_password(request.new_password)
    driver.reset_token = None
    driver.reset_token_expires_at = None
    await db.commit()

    logger.info(f"Contraseña reseteada para: {driver.email}")
    return {"status": "ok", "message": "Contraseña actualizada exitosamente"}


@router.post("/admin-reset-password")
async def admin_reset_password(
    request: AdminResetPasswordRequest,
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Admin asigna una nueva contraseña a un conductor directamente."""
    require_admin(_auth)

    result = await db.execute(
        select(models.Driver).where(models.Driver.id == request.driver_id)
    )
    driver = result.scalar_one_or_none()
    if not driver:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Conductor no encontrado",
        )

    driver.password_hash = hash_password(request.new_password)
    driver.reset_token = None
    driver.reset_token_expires_at = None
    await db.commit()

    logger.info(f"Admin reseteó contraseña de: {driver.email}")
    return {
        "status": "ok",
        "message": f"Contraseña actualizada para {driver.name}",
    }


@router.get("/me")
async def get_me(
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Retorna el perfil del usuario autenticado (JWT) o info admin (API Key)."""
    if isinstance(_auth, dict) and _auth.get("auth_type") == "jwt":
        driver_id = _auth["sub"]
        result = await db.execute(
            select(models.Driver).where(models.Driver.id == driver_id)
        )
        driver = result.scalar_one_or_none()
        if driver:
            return {
                "id": driver.id,
                "name": driver.name,
                "email": driver.email,
                "bus_id": driver.bus_id,
                "company": driver.company,
                "role": driver.role,
                "is_active": driver.is_active,
                "created_at": (
                    driver.created_at.isoformat() if driver.created_at else None
                ),
            }
    elif isinstance(_auth, dict) and _auth.get("auth_type") == "api_key":
        return {
            "role": "admin",
            "auth_type": "api_key",
            "message": "Autenticado como administrador vía API Key",
        }
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="No autenticado"
    )
