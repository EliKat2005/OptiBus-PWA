#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# OptiBus generate_env.sh — Generación segura de .env con secretos aleatorios
# ═══════════════════════════════════════════════════════════════════════
# Uso: ./scripts/generate_env.sh
# Copia .env.example a .env y reemplaza contraseñas por valores aleatorios.
# Después de ejecutar, edita manualmente OPTIBUS_API_KEY en .env
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$SCRIPT_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   OptiBus Env Generator — Secretos Seguros  ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── Validar que .env.example existe ──
if [ ! -f .env.example ]; then
    err "No se encontró .env.example en el directorio raíz."
    exit 1
fi

# ── Generar contraseñas aleatorias ──
# Usar rand -hex para generar contraseñas URL-safe sin caracteres especiales
POSTGRES_PW=$(openssl rand -hex 18)
REDIS_PW=$(openssl rand -hex 18)
GRAFANA_PW=$(openssl rand -hex 18)

log "Contraseñas generadas:"
echo "   POSTGRES_PASSWORD : $POSTGRES_PW"
echo "   REDIS_PASSWORD    : $REDIS_PW"
echo "   GRAFANA_PASSWORD  : $GRAFANA_PW"
echo ""

# ── Copiar .env.example a .env ──
cp .env.example .env
log ".env.example copiado a .env"

# ── Reemplazar contraseñas ──
sed -i "s/^POSTGRES_PASSWORD=.*/POSTGRES_PASSWORD=$POSTGRES_PW/" .env
sed -i "s/^REDIS_PASSWORD=.*/REDIS_PASSWORD=$REDIS_PW/" .env
sed -i "s|^REDIS_URL=.*|REDIS_URL=redis://:${REDIS_PW}@redis:6379/0|" .env
sed -i "s/^GRAFANA_PASSWORD=.*/GRAFANA_PASSWORD=$GRAFANA_PW/" .env

log "Contraseñas inyectadas en .env"

# ── Advertencia sobre OPTIBUS_API_KEY ──
echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ⚠️  FALTA CONFIGURAR MANUALMENTE:                          ║"
echo "║                                                            ║"
echo "║     nano .env    ← edita la variable OPTIBUS_API_KEY=       ║"
echo "║                                                            ║"
echo "║  Genera una key segura con:                                ║"
echo "║     openssl rand -base64 32                                ║"
echo "║                                                            ║"
echo "║  También configura DOMAIN= si tienes dominio propio.       ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""