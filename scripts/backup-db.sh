#!/bin/bash
# DevSecOps: Script de backup automatizado para PostgreSQL/PostGIS
# Uso: ./backup-db.sh [directorio_destino]

set -euo pipefail

# Configuración desde variables de entorno con valores por defecto
BACKUP_DIR="${1:-./backups}"
POSTGRES_USER="${POSTGRES_USER:-optibus}"
POSTGRES_DB="${POSTGRES_DB:-optibus}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_FILE="${BACKUP_DIR}/optibus_backup_${TIMESTAMP}.sql.gz"
RETENTION_DAYS=14 # Modificado de 30 a 14 para optimizar espacio

# Crear directorio de backups
mkdir -p "${BACKUP_DIR}"

echo "[$(date)] Iniciando backup de ${POSTGRES_DB}@${POSTGRES_HOST}:${POSTGRES_PORT}..."

# Realizar backup con pg_dump y comprimir
if PGPASSWORD="${POSTGRES_PASSWORD}" pg_dump \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --no-owner \
    --no-acl \
    --format=custom \
    -Z 9 \
    -f "${BACKUP_FILE}"; then
    
    echo "[$(date)] ✅ Backup exitoso: ${BACKUP_FILE}"
    echo "   Tamaño: $(du -h "${BACKUP_FILE}" | cut -f1)"
else
    echo "[$(date)] ❌ Error al realizar el backup"
    exit 1
fi

# Eliminar backups antiguos (más de RETENTION_DAYS)
find "${BACKUP_DIR}" -name "optibus_backup_*.sql.gz" -mtime +${RETENTION_DAYS} -delete
echo "[$(date)] Backups antiguos limpiados (retención: ${RETENTION_DAYS} días)."

# Opcional: Subir a almacenamiento remoto (descomentar y configurar)
# rclone copy "${BACKUP_FILE}" remote:bucket-backups/
