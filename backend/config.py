"""
OptiBus Configuration — DevSecOps v4.1
Configuración centralizada con validación lazy para evitar crash al importar.
"""

import hashlib
import logging
import os
import re
import sys

# ── Logging seguro para import (sin asumir nada) ──
_log_level = os.getenv("LOG_LEVEL", "INFO").upper()
_log_level_num = getattr(logging, _log_level, logging.INFO)
logging.basicConfig(
    level=_log_level_num,
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    stream=sys.stdout,
    force=True,  # Sobrescribe cualquier config previa (importante para Docker)
)
logger = logging.getLogger("optibus-config")

# ── Database (validación lazy en validate_config()) ──
POSTGRES_USER = os.getenv("POSTGRES_USER", "optibus")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "optibus")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD or ''}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)
ASYNC_DATABASE_URL = DATABASE_URL.replace(
    "postgresql://", "postgresql+asyncpg://"
) if DATABASE_URL.startswith("postgresql://") else DATABASE_URL

# ── Redis ──
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")

# ── CORS ──
ALLOWED_ORIGINS = os.getenv(
    "CORS_ORIGINS", "http://localhost:80,http://localhost,http://127.0.0.1"
).split(",")

# ── API Key ──
OPTIBUS_API_KEY = os.getenv("OPTIBUS_API_KEY", "").strip()
API_KEY_ENABLED = len(OPTIBUS_API_KEY) >= 16

# ── JWT ──
JWT_SECRET_ENV = os.getenv("JWT_SECRET", "").strip()
if JWT_SECRET_ENV and len(JWT_SECRET_ENV) >= 32:
    JWT_SECRET = hashlib.sha256(JWT_SECRET_ENV.encode()).hexdigest()
else:
    _raw = OPTIBUS_API_KEY or "optibus-jwt-secret-dev-only-change-in-production"
    JWT_SECRET = hashlib.sha256(_raw.encode()).hexdigest()

JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "15"))
REFRESH_TOKEN_EXPIRE_DAYS = int(os.getenv("REFRESH_TOKEN_EXPIRE_DAYS", "30"))

# ── Bus Simulator ──
ENABLE_BUS_SIMULATOR = os.getenv("ENABLE_BUS_SIMULATOR", "false").lower() == "true"

# ── WebSocket ──
WS_MAX_MESSAGES_PER_MINUTE = int(os.getenv("WS_MAX_MESSAGES_PER_MINUTE", "60"))
WS_TIMEOUT_SECONDS = int(os.getenv("WS_TIMEOUT_SECONDS", "120"))

# ── Rate Limiting ──
RL_MAX_REQUESTS = int(os.getenv("RL_MAX_REQUESTS", "30"))
RL_WINDOW_SECONDS = int(os.getenv("RL_WINDOW_SECONDS", "60"))

# ── GPS Upload ──
MAX_GPX_UPLOAD_MB = int(os.getenv("MAX_GPX_UPLOAD_MB", "10"))

# ── Trusted Proxy IPs ──
TRUSTED_PROXY_IPS = os.getenv(
    "TRUSTED_PROXY_IPS",
    "127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
).split(",")

# ── Patrones de validación ──
BUS_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.]{1,100}$')
SAFE_ROUTE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ _\-]+$')

# ── Versión ──
APP_VERSION = "0.5.1"


# ─────────────────────────────
# Funciones lazy (NO se ejecutan al importar)
# ─────────────────────────────

def validate_config():
    """Valida la configuración. Se llama en lifespan, NO al importar."""
    if not POSTGRES_PASSWORD:
        raise RuntimeError(
            "POSTGRES_PASSWORD es requerida. Define la variable de entorno o crea un archivo .env"
        )
    if API_KEY_ENABLED:
        logger.info("🔒 API Key auth HABILITADA para endpoints GPS")
    else:
        logger.warning(
            "⚠️  API Key auth DESHABILITADA. Define OPTIBUS_API_KEY (mín. 16 chars) en .env."
        )
    if not JWT_SECRET_ENV or len(JWT_SECRET_ENV) < 32:
        logger.warning(
            "⚠️  JWT_SECRET no configurada independientemente. Derivando de OPTIBUS_API_KEY."
        )
    else:
        logger.info(f"🔑 JWT secret configurado independientemente: hash={JWT_SECRET[:8]}...")


def ensure_directories():
    """Crea directorios necesarios. Se llama en lifespan, NO al importar."""
    from pathlib import Path

    _dir = Path(__file__).resolve().parent / "data" / "recorded_routes"
    _dir.mkdir(parents=True, exist_ok=True, mode=0o755)
    return _dir


RECORDED_ROUTES_DIR = None  # Se inicializa lazy en lifespan


def get_recorded_routes_dir():
    """Obtiene el directorio de rutas grabadas (lazy init)."""
    global RECORDED_ROUTES_DIR
    if RECORDED_ROUTES_DIR is None:
        RECORDED_ROUTES_DIR = ensure_directories()
    return RECORDED_ROUTES_DIR


# ── Validación de IP en red privada (función pura, no depende de estado) ──
import ipaddress


def is_trusted_proxy(ip: str) -> bool:
    """Verifica si una IP está en la lista de proxies confiables (X-Forwarded-For)."""
    if not ip or ip == "unknown":
        return False
    try:
        addr = ipaddress.ip_address(ip.strip())
        for trusted in TRUSTED_PROXY_IPS:
            trusted = trusted.strip()
            if "/" in trusted:
                if addr in ipaddress.ip_network(trusted, strict=False):
                    return True
            elif str(addr) == trusted:
                return True
    except ValueError:
        return False
    return False