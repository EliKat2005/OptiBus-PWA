#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# OptiBus setup_host.sh — Aprovisionamiento de VM Debian 12/13
# ═══════════════════════════════════════════════════════════════════════
# Uso: ./scripts/setup_host.sh
# Ejecutar una sola vez al crear una VM nueva desde cero
# Requiere: Debian 12+ con sudo y conexión a internet
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[+]${NC} $1"; }
warn() { echo -e "${YELLOW}[!]${NC} $1"; }
err()  { echo -e "${RED}[x]${NC} $1"; }

echo ""
echo "╔══════════════════════════════════════════════╗"
echo "║   OptiBus Host Setup — Debian Podman Rootless   ║"
echo "╚══════════════════════════════════════════════╝"
echo ""

# ── 1. Instalar dependencias ──
log "Instalando podman y podman-compose..."
sudo apt update && sudo apt install -y podman podman-compose curl jq

# ── 2. Habilitar linger para procesos en segundo plano ──
log "Habilitando linger para el usuario '$USER'..."
sudo loginctl enable-linger "$USER"

# ── 3. Permitir puertos 80/443 a usuarios sin privilegios ──
log "Configurando puertos no privilegiados (80/443)..."
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80
echo "net.ipv4.ip_unprivileged_port_start=80" | sudo tee /etc/sysctl.d/99-rootless-ports.conf > /dev/null
log "✅ Persistido en /etc/sysctl.d/99-rootless-ports.conf"

# ── 4. Crear directorios de datos ──
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
log "Creando directorios de datos en $SCRIPT_DIR..."
mkdir -p "$SCRIPT_DIR/backend/data/recorded_routes"
mkdir -p "$SCRIPT_DIR/backend/seed_data"
chmod 777 "$SCRIPT_DIR/backend/data/recorded_routes"
log "✅ backend/data/recorded_routes creado (permisos 777)"
log "✅ backend/seed_data creado (coloca aquí tus .gpx y .json para seed_db.sh)"

echo ""
log "Setup completado. Ahora CIERRA y VUELVE a iniciar tu sesión SSH."
log "Luego ejecuta: ./scripts/generate_env.sh"
log "Después: ./deploy.sh"
log "Finalmente: ./scripts/seed_db.sh"
echo ""