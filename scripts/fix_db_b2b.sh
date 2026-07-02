#!/bin/bash
# =============================================
# OptiBus — Migración de columna cooperative_id en producción
# =============================================
# Uso: ./scripts/fix_db_b2b.sh
# Añade la columna cooperative_id a tablas existentes
# y asigna la Cooperativa 28 de Septiembre (ID=1) por defecto.
# =============================================
set -euo pipefail

GREEN='\033[0;32m'; NC='\033[0m'
log() { echo -e "${GREEN}[$(date '+%H:%M:%S')]${NC} $1"; }

log "Ejecutando migracion de cooperative_id en produccion..."

podman exec -i optibus_db psql -U optibus -d optibus_prod <<'SQL'
-- Añadir columnas cooperative_id si no existen
ALTER TABLE bus_positions ADD COLUMN IF NOT EXISTS cooperative_id INTEGER DEFAULT 1;
ALTER TABLE routes ADD COLUMN IF NOT EXISTS cooperative_id INTEGER DEFAULT 1;
ALTER TABLE stops ADD COLUMN IF NOT EXISTS cooperative_id INTEGER DEFAULT 1;
ALTER TABLE drivers ADD COLUMN IF NOT EXISTS cooperative_id INTEGER DEFAULT 1;

-- Crear cooperativa default si no existe
INSERT INTO cooperatives (id, name, slug, api_key_hash, max_buses, is_active)
VALUES (1, 'Cooperativa 28 de Septiembre', 'coop-28-septiembre', 'default', 50, true)
ON CONFLICT (id) DO NOTHING;

-- Actualizar registros sin cooperative_id
UPDATE bus_positions SET cooperative_id = 1 WHERE cooperative_id IS NULL;
UPDATE routes SET cooperative_id = 1 WHERE cooperative_id IS NULL;
UPDATE stops SET cooperative_id = 1 WHERE cooperative_id IS NULL;
UPDATE drivers SET cooperative_id = 1 WHERE cooperative_id IS NULL;

-- Crear indices
CREATE INDEX IF NOT EXISTS idx_bus_positions_cooperative ON bus_positions(cooperative_id, recorded_at);
CREATE INDEX IF NOT EXISTS idx_routes_cooperative ON routes(cooperative_id);
CREATE INDEX IF NOT EXISTS idx_stops_cooperative ON stops(cooperative_id);
CREATE INDEX IF NOT EXISTS idx_drivers_cooperative ON drivers(cooperative_id, is_active);
SQL

log "Migracion completada. Todas las tablas tienen cooperative_id = 1."