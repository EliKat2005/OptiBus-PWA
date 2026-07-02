#!/bin/bash
# =============================================
# OptiBus — Backup Encriptado + Azure Blob Upload
# =============================================
# Uso: ./scripts/backup-db-encrypted.sh
# Requiere: openssl, pg_dump, gzip
# Opcional: az (Azure CLI) para subir a Azure Blob Storage
# =============================================
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
BACKUP_DIR="${ROOT_DIR}/.backups"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/optibus_${TIMESTAMP}.sql.gz.enc"
BACKUP_KEY="${BACKUP_ENCRYPTION_KEY:-}"
AZ_STORAGE_ACCOUNT="${AZ_STORAGE_ACCOUNT:-}"
AZ_CONTAINER="${AZ_BACKUP_CONTAINER:-optibus-backups}"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
log()  { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date '+%H:%M:%S')]${NC} $1"; }
err()  { echo -e "${RED}[$(date '+%H:%M:%S')]${NC} $1"; }

if [ -z "$BACKUP_KEY" ]; then
    err "BACKUP_ENCRYPTION_KEY no definida."
    echo "   Genera una key: openssl rand -base64 32"
    echo "   Exportala: export BACKUP_ENCRYPTION_KEY=..."
    exit 1
fi

mkdir -p "$BACKUP_DIR"

log "Creando pg_dump de PostGIS..."
PGPASSWORD="${POSTGRES_PASSWORD:-}" pg_dump \
    -h "${POSTGRES_HOST:-localhost}" \
    -U "${POSTGRES_USER:-optibus}" \
    -d "${POSTGRES_DB:-optibus_prod}" \
    --no-owner --no-acl 2>/dev/null \
    | gzip \
    | openssl enc -aes-256-cbc -salt -pbkdf2 -pass "pass:${BACKUP_KEY}" -out "$BACKUP_FILE"

log "Backup encriptado: ${BACKUP_FILE}"

# ── Azure Blob (opcional) ──
if [ -n "$AZ_STORAGE_ACCOUNT" ] && command -v az &>/dev/null; then
    log "Subiendo a Azure Blob..."
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
    warn "No se pudo subir a Azure. Backup solo local."
else
    warn "Azure CLI no configurada. Backup local: ${BACKUP_FILE}"
fi

# ── Limpiar backups antiguos (conservar últimos 7) ──
ls -t "${BACKUP_DIR}"/optibus_*.sql.gz.enc 2>/dev/null | tail -n +8 | xargs -r rm
log "Backups antiguos eliminados. Conservados los 7 mas recientes."

log "Backup completado exitosamente."