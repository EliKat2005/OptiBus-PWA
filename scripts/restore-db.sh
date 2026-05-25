#!/bin/bash
# DevSecOps: Script de restauración de backup PostgreSQL/PostGIS
# Uso: ./restore-db.sh <archivo_backup.sql.gz>

set -euo pipefail

if [ $# -lt 1 ]; then
    echo "Uso: $0 <archivo_backup.sql.gz>"
    echo "Ejemplo: $0 ./backups/optibus_backup_20250101_120000.sql.gz"
    exit 1
fi

BACKUP_FILE="$1"
POSTGRES_USER="${POSTGRES_USER:-optibus}"
POSTGRES_DB="${POSTGRES_DB:-optibus}"
POSTGRES_HOST="${POSTGRES_HOST:-localhost}"
POSTGRES_PORT="${POSTGRES_PORT:-5432}"

if [ ! -f "$BACKUP_FILE" ]; then
    echo "❌ El archivo de backup '$BACKUP_FILE' no existe."
    exit 1
fi

echo "⚠️  ADVERTENCIA: Esto SOBREESCRIBIRÁ la base de datos '${POSTGRES_DB}'"
echo "   Host: ${POSTGRES_HOST}:${POSTGRES_PORT}"
echo "   Archivo: ${BACKUP_FILE}"
echo ""
read -p "¿Estás seguro de continuar? (escribe 'SI' en mayúsculas): " CONFIRM

if [ "$CONFIRM" != "SI" ]; then
    echo "Restauración cancelada."
    exit 0
fi

echo "[$(date)] Iniciando restauración de ${POSTGRES_DB}..."

# Restaurar desde backup comprimido
if gunzip -c "${BACKUP_FILE}" | PGPASSWORD="${POSTGRES_PASSWORD}" psql \
    -h "${POSTGRES_HOST}" \
    -p "${POSTGRES_PORT}" \
    -U "${POSTGRES_USER}" \
    -d "${POSTGRES_DB}" \
    --single-transaction \
    --set ON_ERROR_STOP=on; then
    echo "[$(date)] ✅ Restauración completada exitosamente."
else
    echo "[$(date)] ❌ Error durante la restauración."
    exit 1
fi