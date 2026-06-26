"""
OptiBus Auth Utilities — DevSecOps v4.0
JWT creation/validation, password hashing, and API key verification.
Separado de main.py para mantener modularidad y testabilidad.
"""

import base64
import hashlib
import hmac as hmac_lib
import json
import logging
from datetime import UTC, datetime
from secrets import compare_digest

from config import (
    ACCESS_TOKEN_EXPIRE_MINUTES,
    API_KEY_ENABLED,
    JWT_SECRET,
    OPTIBUS_API_KEY,
    REFRESH_TOKEN_EXPIRE_DAYS,
)
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger("optibus-auth")

security = HTTPBearer(auto_error=False)


# ──────────────────────────────────────────────
# Password Hashing
# ──────────────────────────────────────────────


def hash_password(password: str) -> str:
    """Hash bcrypt con salt automático (12 rounds)."""
    import bcrypt

    return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(password: str, password_hash: str) -> bool:
    """Verifica contraseña contra hash bcrypt o SHA-256 (retrocompatibilidad)."""
    if password_hash.startswith("$2b$") or password_hash.startswith("$2a$"):
        import bcrypt

        try:
            return bcrypt.checkpw(password.encode(), password_hash.encode())
        except Exception:
            return False

    # Retrocompatibilidad con hashes SHA-256 antiguos
    try:
        salt, hashed = password_hash.split(":", 1)
        return compare_digest(
            hashlib.sha256(f"{salt}:{password}".encode()).hexdigest(), hashed
        )
    except (ValueError, AttributeError):
        return False


# ──────────────────────────────────────────────
# JWT Utilities
# ──────────────────────────────────────────────


def _now_ts() -> float:
    """Timestamp UNIX actual (UTC)."""
    return datetime.now(UTC).timestamp()


def _b64url_encode(data: bytes) -> str:
    """Codifica bytes a base64url sin padding."""
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _b64url_decode(data: str) -> bytes:
    """Decodifica base64url a bytes (maneja padding automáticamente)."""
    padding = -len(data) % 4
    return base64.urlsafe_b64decode(data + "=" * padding)


def create_jwt_token(
    driver_id: int, bus_id: str, role: str, token_type: str = "access"
) -> str:
    """Genera un JWT firmado manualmente (HMAC-SHA256)."""
    now_ts = int(_now_ts())
    if token_type == "access":
        exp_ts = now_ts + (ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    else:
        exp_ts = now_ts + (REFRESH_TOKEN_EXPIRE_DAYS * 86400)

    payload = {
        "sub": driver_id,
        "bus_id": bus_id,
        "role": role,
        "type": token_type,
        "iat": now_ts,
        "exp": exp_ts,
    }

    header = {"alg": "HS256", "typ": "JWT"}
    header_b64 = _b64url_encode(
        json.dumps(header, separators=(",", ":")).encode()
    )
    payload_b64 = _b64url_encode(
        json.dumps(payload, separators=(",", ":")).encode()
    )

    msg = f"{header_b64}.{payload_b64}".encode()
    key = JWT_SECRET.encode() if isinstance(JWT_SECRET, str) else JWT_SECRET
    sig = _b64url_encode(hmac_lib.new(key, msg, hashlib.sha256).digest())

    return f"{header_b64}.{payload_b64}.{sig}"


def decode_jwt_token(token: str) -> dict:
    """Decodifica y valida un JWT manualmente (HMAC-SHA256)."""
    try:
        parts = token.split(".")
        if len(parts) != 3:
            raise ValueError("Malformed JWT: expected 3 parts")
        header_b64, payload_b64, sig_b64 = parts

        # Verificar firma
        msg = f"{header_b64}.{payload_b64}".encode()
        key = JWT_SECRET.encode() if isinstance(JWT_SECRET, str) else JWT_SECRET
        expected_sig = hmac_lib.new(key, msg, hashlib.sha256).digest()
        received_sig = _b64url_decode(sig_b64)
        if not compare_digest(expected_sig, received_sig):
            raise ValueError("Signature verification failed")

        # Decodificar payload
        payload = json.loads(_b64url_decode(payload_b64).decode("utf-8"))

        # Validar claims
        exp = payload.get("exp", 0)
        if _now_ts() > exp:
            raise ValueError("Token expired")
        if "sub" not in payload or "type" not in payload:
            raise ValueError("Missing required claims: sub or type")

        return payload
    except ValueError:
        raise
    except Exception as e:
        logger.error(f"JWT decode failed: {type(e).__name__}: {e}")
        raise ValueError(str(e)) from e


# ──────────────────────────────────────────────
# API Key + JWT Verification (FastAPI Dependency)
# ──────────────────────────────────────────────


async def verify_api_key(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """
    DevSecOps: Verificación de autenticación obligatoria.
    - Si API_KEY_ENABLED es False, DENIEGA el acceso (no acceso público por defecto).
    - Acepta API Key estática O JWT válido.
    - Nunca expone detalles del token en errores.
    """
    # Si la API Key no está configurada, NO permitimos acceso público
    # (a menos que sea un endpoint explícitamente público)
    if not API_KEY_ENABLED:
        return {
            "auth_type": "disabled",
            "role": "public",
            "note": "API Key no configurada — acceso restringido",
        }

    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Autenticación requerida. Usa Authorization: Bearer <token>",
        )

    token = credentials.credentials

    # Intento 1: API Key estática (admin)
    if compare_digest(token, OPTIBUS_API_KEY):
        return {"auth_type": "api_key", "role": "admin"}

    # Intento 2: JWT (conductor/admin)
    try:
        payload = decode_jwt_token(token)
        payload["auth_type"] = "jwt"
        return payload
    except ValueError as e:
        error_msg = str(e)
        if "expired" in error_msg.lower() or "expired" in error_msg.lower():
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Token expirado. Usa /api/auth/refresh",
            ) from e
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido",
        ) from e


async def verify_optional_auth(
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> dict:
    """Autenticación opcional: intenta autenticar pero no falla si no hay token."""
    if not API_KEY_ENABLED:
        return {
            "auth_type": "disabled",
            "role": "public",
            "note": "API Key no configurada",
        }

    if credentials is None:
        return {"auth_type": "none", "role": "public"}

    token = credentials.credentials

    if compare_digest(token, OPTIBUS_API_KEY):
        return {"auth_type": "api_key", "role": "admin"}

    try:
        payload = decode_jwt_token(token)
        payload["auth_type"] = "jwt"
        return payload
    except Exception:
        return {"auth_type": "none", "role": "public", "note": "invalid_token"}


def require_admin(auth: dict) -> None:
    """Verifica que el usuario autenticado tenga rol de admin."""
    if not isinstance(auth, dict) or auth.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Solo administradores pueden realizar esta acción",
        )


def require_auth_enabled() -> None:
    """Verifica que la autenticación esté habilitada (API_KEY configurada)."""
    if not API_KEY_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="API Key no configurada. Contacta al administrador.",
        )
