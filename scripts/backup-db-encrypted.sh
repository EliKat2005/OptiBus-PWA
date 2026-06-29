"""
OptiBus Security Middleware — DevSecOps v5.0
Rate limiting, JWT blocklist, y hardening de la API.
"""

import hashlib
import logging
import time
from datetime import UTC, datetime

from fastapi import Request
from rate_limiter import get_redis

logger = logging.getLogger("optibus-security")


# ═══════════════════════════════════════════════════════════════════════
# Rate Limiting por endpoint (sin dependencia de slowapi)
# ═══════════════════════════════════════════════════════════════════════

# Límites por endpoint (requests/minuto)
RATE_LIMITS = {
    "/api/routes": 30,           # Rutas: 30 req/min
    "/api/stops/nearby": 20,      # Paradas cercanas: 20 req/min
    "/api/stops/search": 30,      # Búsqueda: 30 req/min
    "/api/gps/update": 120,       # GPS desde APK: 120 req/min (2 por segundo)
    "/api/routes/plan": 20,       # Planificador: 20 req/min
    "/api/routes/upload": 10,     # Upload GPX: 10 req/min
    "/admin": 10,                 # Admin dashboard: 10 req/min
    "/api/auth/login": 10,        # Login: 10 req/min
    "/api/auth/register": 5,      # Registro: 5 req/min
    "/health": 60,                # Health: 60 req/min
    "default": 60,                # Otros: 60 req/min
}


async def rate_limit_by_path(request: Request, client_ip: str) -> bool:
    """
    Rate limiting específico por ruta del endpoint.
    Retorna True si la petición debe ser rechazada (429).
    """
    path = request.url.path
    max_req = RATE_LIMITS.get("default")
    for prefix, limit in RATE_LIMITS.items():
        if path.startswith(prefix) and limit < max_req:
            max_req = limit

    r = await get_redis()
    if r:
        key = f"rl:path:{client_ip}:{path}"
        window = 60  # 1 minuto
        current = await r.incr(key)
        if current == 1:
            await r.expire(key, window)
        if current > max_req:
            logger.warning(f"Rate limit ({path}): {client_ip} ({current}/{max_req})")
            return True
    return False


# ═══════════════════════════════════════════════════════════════════════
# JWT Blocklist (revocación de tokens)
# ═══════════════════════════════════════════════════════════════════════

async def revoke_jwt(jti: str, ttl_seconds: int = 43200) -> bool:
    """
    Añade un JWT a la blocklist en Redis.
    TTL por defecto: 12 horas (43200 segundos).
    """
    r = await get_redis()
    if r:
        key = f"jwt:bl:{jti}"
        await r.setex(key, ttl_seconds, "1")
        logger.info(f"JWT revocado: {jti[:10]}... (TTL={ttl_seconds}s)")
        return True
    logger.warning("JWT blocklist: Redis no disponible. Revocación en memoria no persistente.")
    return False


async def is_jwt_revoked(jti: str) -> bool:
    """Verifica si un JWT está en la blocklist."""
    r = await get_redis()
    if r:
        return await r.exists(f"jwt:bl:{jti}") > 0
    return False


async def cleanup_expired_blocklist() -> int:
    """Limpia entradas expiradas de la blocklist (Redis lo maneja con TTL automático)."""
    return 0  # Redis se encarga de expirar las keys con SETEX


# ═══════════════════════════════════════════════════════════════════════
# Helper para generar JTI (JWT ID)
# ═══════════════════════════════════════════════════════════════════════

def generate_jti() -> str:
    """Genera un JWT ID único para revocación."""
    return hashlib.sha256(f"{time.time()}-{id(object())}".encode()).hexdigest()[:16]
</content>

<write_to_file>
<path>scripts/backup-db-encrypted.sh</path>
<content>
#!/bin/bash
# =============================================
# OptiBus — Backup Encriptado + Azure Blob Upload
# =============================================
# Uso: ./scripts/backup-db-encrypted.sh
# Requiere: openssl, az (Azure CLI), pg_dump
# =============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

# ── Configuración ──
BACKUP_DIR="${ROOT_DIR}/.backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/optibus_${TIMESTAMP}.sql.gz.enc"
BACKUP_KEY="${BACKUP_ENCRYPTION_KEY:-}"

# Azure Blob Storage
AZ_CONTAINER="${AZ_BACKUP_CONTAINER:-optibus-backups}"
AZ_STORAGE_ACCOUNT="${AZ_STORAGE_ACCOUNT:-}"

# ── Colores ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date +'%H:%M:%S')] ⚠️  $1${NC}"; }
err()  { echo -e "${RED}[$(date +'%H:%M:%S')] ❌ $1${NC}"; }

# ── Validación ──
if [ -z "$BACKUP_KEY" ]; then
    err "BACKUP_ENCRYPTION_KEY no está definida. Define la variable de entorno."
    err "Genera una key: openssl rand -base64 32"
    exit 1
fi

mkdir -p "$BACKUP_DIR"

# ── 1. Dump de PostGIS ──
log "Creando dump de PostgreSQL..."
PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
    -h "${POSTGRES_HOST:-localhost}" \
    -U "${POSTGRES_USER:-optibus}" \
    -d "${POSTGRES_DB:-optibus_prod}" \
    --no-owner --no-acl \
    | gzip \
    | openssl enc -aes-256-cbc -salt -pbkdf2 -pass "pass:${BACKUP_KEY}" \
    -out "$BACKUP_FILE"

log "✅ Backup encriptado: ${BACKUP_FILE}"

# ── 2. Subir a Azure Blob (si está configurado) ──
if [ -n "$AZ_STORAGE_ACCOUNT" ] && command -v az &>/dev/null; then
    log "Subiendo a Azure Blob Storage..."
    az storage blob upload \
        --account-name "$AZ_STORAGE_ACCOUNT" \
        --container-name "$AZ_CONTAINER" \
        --file "$BACKUP_FILE" \
        --name "optibus_${TIMESTAMP}.sql.gz.enc" \
        --auth-mode login 2>/dev/null || \
    az storage blob upload \
        --account-name "$AZ_STORAGE_ACCOUNT" \
        --container-name "$AZ_CONTAINER" \
        --file "$BACKUP_FILE" \
        --name "optibus_${TIMESTAMP}.sql.gz.enc" \
        --connection-string "${AZURE_STORAGE_CONNECTION_STRING:-}" 2>/dev/null || \
    warn "No se pudo subir a Azure. ¿Está configurado AZ_STORAGE_ACCOUNT o AZURE_STORAGE_CONNECTION_STRING?"
else
    warn "Azure CLI no instalada o AZ_STORAGE_ACCOUNT no configurada. Backup solo local."
    log "Copia el archivo manualmente: ${BACKUP_FILE}"
fi

# ── 3. Limpiar backups antiguos (mantener últimos 7) ──
ls -t "${BACKUP_DIR}"/optibus_*.sql.gz.enc 2>/dev/null | tail -n +8 | xargs -r rm
log "🧹 Backups antiguos eliminados. Se conservan los 7 más recientes."

log "🎉 Backup completado exitosamente."