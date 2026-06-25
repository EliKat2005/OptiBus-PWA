"""
OptiBus Configuration — DevSecOps v4.0
Centraliza todas las variables de entorno, constantes y configuración.
"""

import hashlib
import logging
import os
import re

# ── Logging ──
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("optibus-config")

# ── Database ──
POSTGRES_USER = os.getenv("POSTGRES_USER", "optibus")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
if not POSTGRES_PASSWORD:
    raise RuntimeError(
        "POSTGRES_PASSWORD es requerida. Define la variable de entorno o crea un archivo .env"
    )
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "optibus")

DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
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

if API_KEY_ENABLED:
    logger.info("API Key auth HABILITADA para endpoints GPS")
else:
    logger.warning(
        "⚠️  API Key auth DESHABILITADA. Define OPTIBUS_API_KEY (mín. 16 chars) en .env. "
        "Todos los endpoints de escritura estarán restringidos hasta que configures una API Key."
    )

# ── JWT ──
# DevSecOps: JWT_SECRET INDEPENDIENTE de API Key (no compartir secretos)
JWT_SECRET_ENV = os.getenv("JWT_SECRET", "").strip()
if JWT_SECRET_ENV and len(JWT_SECRET_ENV) >= 32:
    JWT_SECRET = hashlib.sha256(JWT_SECRET_ENV.encode()).hexdigest()
    logger.info(f"JWT initialized from JWT_SECRET env: hash={JWT_SECRET[:8]}...")
else:
    # Fallback: derivar de API_KEY si JWT_SECRET no está configurado
    # NOTA: Esto es un fallback para desarrollo. En producción, define JWT_SECRET independiente.
    _raw = OPTIBUS_API_KEY or "optibus-jwt-secret-dev-only-change-in-production"
    JWT_SECRET = hashlib.sha256(_raw.encode()).hexdigest()
    if not JWT_SECRET_ENV:
        logger.warning(
            "JWT_SECRET no configurada. Derivando de OPTIBUS_API_KEY. "
            "⚠️  Define JWT_SECRET independiente en .env para producción."
        )

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

# ── Trusted Proxy IPs (para X-Forwarded-For validation) ──
TRUSTED_PROXY_IPS = os.getenv(
    "TRUSTED_PROXY_IPS",
    "127.0.0.1,10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
).split(",")

# ── Validación de IP en red privada ──
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
            else:
                if str(addr) == trusted:
                    return True
    except ValueError:
        return False
    return False

# ── Patrones de validación ──
BUS_ID_PATTERN = re.compile(r'^[a-zA-Z0-9_\-\.]{1,100}$')
SAFE_ROUTE_NAME_PATTERN = re.compile(r'^[a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ _\-]+$')

# ── Directorios ──
from pathlib import Path
RECORDED_ROUTES_DIR = Path(__file__).parent / "data" / "recorded_routes"
RECORDED_ROUTES_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)

# ── Versión ──
APP_VERSION = "0.5.0"