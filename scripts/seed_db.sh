#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# OptiBus seed_db.sh — Auto-ingesta de rutas y paradas desde seed_data/
# ═══════════════════════════════════════════════════════════════════════
# Uso: ./scripts/seed_db.sh
# Coloca archivos .gpx y .json en backend/seed_data/ antes de ejecutar.
# El script empareja archivos por nombre base.
#
# Ejemplo de estructura esperada:
#   backend/seed_data/ruta_Santo_Domingo_20260602.gpx
#   backend/seed_data/paradas_Santo_Domingo_20260602.json
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

SEED_DIR="$SCRIPT_DIR/backend/seed_data"
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║     OptiBus Seed DB — Ingesta de Rutas      ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Validar que el contenedor API esté corriendo ──
if ! podman ps --filter name=optibus_api --format '{{.Names}}' | grep -q optibus_api; then
    err "El contenedor optibus_api no está corriendo."
    echo -e "${RED}   Ejecuta ./deploy.sh primero.${NC}"
    exit 1
fi

# ── Validar que existan archivos en seed_data/ ──
if [ ! -d "$SEED_DIR" ] || [ -z "$(ls -A "$SEED_DIR" 2>/dev/null)" ]; then
    err "No se encontraron archivos en $SEED_DIR/"
    echo -e "${RED}   Coloca tus archivos .gpx y .json ahí antes de ejecutar.${NC}"
    exit 1
fi

# ── Contar archivos ──
GPX_COUNT=$(find "$SEED_DIR" -maxdepth 1 -name '*.gpx' | wc -l)
JSON_COUNT=$(find "$SEED_DIR" -maxdepth 1 -name '*.json' | wc -l)
log "Encontrados: $GPX_COUNT archivos GPX, $JSON_COUNT archivos JSON"

# ── Iterar sobre cada .gpx ──
INGESTED=0
SKIPPED=0

find "$SEED_DIR" -maxdepth 1 -name '*.gpx' | sort | while read -r GPX_FILE; do
    BASENAME=$(basename "$GPX_FILE" .gpx)
    # Extraer nombre base sin prefijo 'ruta_'
    CLEAN_NAME=$(echo "$BASENAME" | sed 's/^ruta_//' | tr '_' ' ')
    # Extraer timestamp del nombre si existe
    echo ""
    log "Procesando: $BASENAME → nombre: '$CLEAN_NAME'"

    # Ingesta del GPX
    echo "   Ingestando ruta..."
    if podman exec optibus_api python3 ingest_gpx.py "backend/seed_data/$(basename "$GPX_FILE")" "$CLEAN_NAME"; then
        echo -e "   ${GREEN}✅ Ruta ingerida${NC}"
    else
        echo -e "   ${RED}❌ Fallo la ingesta del GPX${NC}"
    fi

    # Buscar paradas correspondientes
    JSON_FILE_1="${SEED_DIR}/paradas_${BASENAME}.json"
    JSON_FILE_2="${SEED_DIR}/$(echo "$BASENAME" | sed 's/^ruta_/paradas_/').json"

    if [ -f "$JSON_FILE_1" ]; then
        echo "   Encontrado archivo de paradas: $(basename "$JSON_FILE_1")"
        echo "   Ingestando paradas..."
        if podman exec optibus_api python3 ingest_stops.py "backend/seed_data/$(basename "$JSON_FILE_1")"; then
            echo -e "   ${GREEN}✅ Paradas ingeridas${NC}"
        else
            echo -e "   ${RED}❌ Fallo la ingesta de paradas${NC}"
        fi
        INGESTED=$((INGESTED + 1))
    elif [ -f "$JSON_FILE_2" ]; then
        echo "   Encontrado archivo de paradas: $(basename "$JSON_FILE_2")"
        echo "   Ingestando paradas..."
        if podman exec optibus_api python3 ingest_stops.py "backend/seed_data/$(basename "$JSON_FILE_2")"; then
            echo -e "   ${GREEN}✅ Paradas ingeridas${NC}"
        else
            echo -e "   ${RED}❌ Fallo la ingesta de paradas${NC}"
        fi
        INGESTED=$((INGESTED + 1))
    else
        warn "   No se encontró archivo JSON de paradas para '$BASENAME'"
        SKIPPED=$((SKIPPED + 1))
    fi
done

echo ""
log "Ingesta completada. Rutas procesadas."
log "Verifica con: ./deploy.sh --status"
echo ""