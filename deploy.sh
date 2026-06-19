#!/bin/bash
# ═══════════════════════════════════════════════════════════════════════
# OptiBus Deploy Script — DevSecOps Production Grade
# ═══════════════════════════════════════════════════════════════════════
# Uso:
#   ./deploy.sh              → Despliegue normal (build + up)
#   ./deploy.sh --quick      → Solo restart (sin rebuild)
#   ./deploy.sh --rollback   → Revertir al backup anterior
#   ./deploy.sh --status     → Ver estado de servicios
# ═══════════════════════════════════════════════════════════════════════
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colores para output profesional
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

log()  { echo -e "${GREEN}[$(date +'%H:%M:%S')]${NC} $1"; }
warn() { echo -e "${YELLOW}[$(date +'%H:%M:%S')] ⚠️  $1${NC}"; }
err()  { echo -e "${RED}[$(date +'%H:%M:%S')] ❌ $1${NC}"; }
info() { echo -e "${CYAN}[$(date +'%H:%M:%S')] ℹ️  $1${NC}"; }

# ──────────────────────────────────────────────
# Validación de pre-requisitos
# ──────────────────────────────────────────────
validate_env() {
    # ── Pre-flight 1: Podman instalado y respondiendo ──
    if ! command -v podman &>/dev/null; then
        err "Podman no está instalado. Ejecuta: sudo apt install podman podman-compose"
        exit 1
    fi
    if ! podman info &>/dev/null; then
        err "Podman está instalado pero no responde. Verifica: podman info"
        exit 1
    fi

    # ── Pre-flight 2: .env existe ──
    if [ ! -f .env ]; then
        err "Archivo .env no existe."
        echo -e "${RED}   Ejecuta: ./scripts/generate_env.sh${NC}"
        echo -e "${RED}   Luego edita tu API Key con: nano .env${NC}"
        exit 1
    fi

    # ── Pre-flight 3: Puertos no privilegiados ──
    local unpriv_port
    unpriv_port=$(cat /proc/sys/net/ipv4/ip_unprivileged_port_start 2>/dev/null || echo "1024")
    if [ "$unpriv_port" -gt 80 ]; then
        err "net.ipv4.ip_unprivileged_port_start = $unpriv_port (debe ser <= 80)"
        echo -e "${RED}   Ejecuta manualmente:${NC}"
        echo -e "${RED}   sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80${NC}"
        echo -e "${RED}   echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/99-rootless-ports.conf${NC}"
        exit 1
    fi

    # Cargar variables para validación (solo lectura segura)
    DOMAIN=$(grep -E '^DOMAIN=' .env | cut -d= -f2- | tr -d '"' || echo "localhost")
    POSTGRES_PASSWORD=$(grep -E '^POSTGRES_PASSWORD=' .env | cut -d= -f2- | tr -d '"' || echo "")

    if [ "$DOMAIN" = "localhost" ]; then
        warn "DOMAIN=localhost → Solo HTTP, sin SSL automático."
    fi

    if [ -z "$POSTGRES_PASSWORD" ] || [ "$POSTGRES_PASSWORD" = "CHANGEME_SECURE_PASSWORD" ]; then
        err "POSTGRES_PASSWORD no configurada o usa el valor por defecto. Ejecuta: ./scripts/generate_env.sh"
        exit 1
    fi

    log "✅ Entorno validado. DOMAIN=$DOMAIN"
}

# ──────────────────────────────────────────────
# Backup pre-deploy (para rollback)
# ──────────────────────────────────────────────
backup_before_deploy() {
    local BACKUP_DIR=".deploy_backups"
    local TIMESTAMP
    TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
    mkdir -p "$BACKUP_DIR"

    info "Creando backup pre-deploy..."

    # Guardar estados de volúmenes
    if podman volume ls | grep -q optibus-pwa_db_data; then
        podman run --rm -v optibus-pwa_db_data:/data -v "$(pwd)/$BACKUP_DIR":/backup \
            docker.io/library/alpine:latest \
            tar czf "/backup/db_data_${TIMESTAMP}.tar.gz" -C /data . 2>/dev/null || warn "Backup DB parcial"
    fi

    # Guardar git commit actual
    git rev-parse HEAD > "$BACKUP_DIR/git_commit_${TIMESTAMP}.txt" 2>/dev/null || true

    # Limpiar backups antiguos (>5)
    ls -t "$BACKUP_DIR"/git_commit_*.txt 2>/dev/null | tail -n +6 | xargs -r rm
    ls -t "$BACKUP_DIR"/db_data_*.tar.gz 2>/dev/null | tail -n +6 | xargs -r rm

    log "✅ Backup guardado en $BACKUP_DIR/"
}

# ──────────────────────────────────────────────
# Rollback
# ──────────────────────────────────────────────
do_rollback() {
    local BACKUP_DIR=".deploy_backups"
    local LATEST
    LATEST=$(ls -t "$BACKUP_DIR"/db_data_*.tar.gz 2>/dev/null | head -1)

    warn "Iniciando ROLLBACK..."

    podman-compose down 2>/dev/null || true

    if [ -n "$LATEST" ]; then
        info "Restaurando backup: $LATEST"
        podman run --rm -v optibus-pwa_db_data:/data -v "$(pwd)/$BACKUP_DIR":/backup \
            docker.io/library/alpine:latest \
            sh -c "rm -rf /data/* && tar xzf /backup/$(basename "$LATEST") -C /data" 2>/dev/null || warn "Restauración parcial"
    fi

    podman-compose up -d
    wait_for_health
    log "✅ Rollback completado."
}

# ──────────────────────────────────────────────
# Esperar a que la API esté healthy
# ──────────────────────────────────────────────
wait_for_health() {
    info "Esperando health de la API (máx 90s)..."
    for i in $(seq 1 90); do
        if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
            local HEALTH_JSON
            HEALTH_JSON=$(curl -s http://localhost:8000/health 2>/dev/null)
            if command -v python3 &>/dev/null; then
                log "✅ API healthy en ${i}s: $(echo "$HEALTH_JSON" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(f"DB={d.get(\"database\",\"?\")} Redis={d.get(\"redis\",\"?\")} v={d.get(\"version\",\"?\")}\")' 2>/dev/null || echo 'ok')"
            else
                log "✅ API healthy en ${i}s: $(echo "$HEALTH_JSON" | grep -o '"status":"[^"]*"' | sed 's/"status":"//;s/"//' || echo 'ok')"
            fi
            return 0
        fi
        [ $((i % 15)) -eq 0 ] && info "   ... ${i}s esperando"
        sleep 1
    done
    err "API no respondió después de 90s."
    return 1
}

# ──────────────────────────────────────────────
# Despliegue completo
# ──────────────────────────────────────────────
do_deploy() {
    local QUICK="${1:-false}"

    log "🚀 Iniciando despliegue OptiBus..."

    if [ "$QUICK" = "false" ]; then
        # Pull de imágenes base
        info "Actualizando imágenes base..."
        podman-compose pull 2>/dev/null || warn "Pull parcial (sin conexión externa?)"

        # Reconstruir API sin cache
        info "Reconstruyendo imagen de API..."
        podman-compose build api --no-cache

        # Backup pre-deploy
        backup_before_deploy
    fi

    # Reiniciar servicios
    info "Reiniciando servicios..."
    podman-compose down 2>/dev/null || true
    podman-compose up -d

    # Esperar health
    wait_for_health || {
        warn "API no healthy. Iniciando rollback automático..."
        do_rollback
        exit 1
    }

    # Limpieza de imágenes huérfanas
    info "Limpiando imágenes huérfanas..."
    podman image prune -f 2>/dev/null || true

    log "✅ Despliegue completado exitosamente."
    echo ""
    log "🌐 Frontend:  https://${DOMAIN:-localhost}"
    log "🏥 Health:    https://${DOMAIN:-localhost}/health"
    log "📊 Métricas:  http://localhost:8000/metrics (solo local)"
    log "📈 Grafana:   http://localhost:3000 (solo local, login: admin)"
}

# ──────────────────────────────────────────────
# Status check
# ──────────────────────────────────────────────
do_status() {
    echo "╔══════════════════════════════════════════════════╗"
    echo "║         OptiBus Status - $(date '+%Y-%m-%d %H:%M')         ║"
    echo "╚══════════════════════════════════════════════════╝"

    echo ""
    echo "📦 Contenedores:"
    podman ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}" --filter name=optibus 2>/dev/null || echo "   Sin contenedores corriendo"

    echo ""
    echo "💾 Volúmenes:"
    podman volume ls --filter name=optibus 2>/dev/null || echo "   Sin volúmenes"

    echo ""
    echo "🏥 API Health:"
    if curl -sf http://localhost:8000/health >/dev/null 2>&1; then
        curl -s http://localhost:8000/health | python3 -m json.tool 2>/dev/null || echo "   OK (no JSON)"
    else
        echo "   ❌ No responde"
    fi

    echo ""
    echo "🗺️  Rutas en BD:"
    podman exec optibus_api python3 -c "
import asyncio
from database import SessionLocal
from models import Route
from sqlalchemy import select, func

async def count():
    async with SessionLocal() as s:
        r = await s.execute(select(func.count(Route.id)))
        return r.scalar()

print(f'   {asyncio.run(count())} rutas')
" 2>/dev/null || echo "   ❌ No se pudo consultar"

    echo ""
    echo "📊 Prometheus:"
    curl -sf http://localhost:9090/-/healthy >/dev/null 2>&1 && echo "   ✅ Healthy" || echo "   ❌ No responde"

    echo ""
    echo "📈 Grafana:"
    curl -sf http://localhost:3000/api/health >/dev/null 2>&1 && echo "   ✅ Healthy" || echo "   ❌ No responde"
}

# ──────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────
case "${1:-}" in
    --quick)
        validate_env
        do_deploy true
        ;;
    --rollback)
        validate_env
        do_rollback
        ;;
    --status)
        do_status
        ;;
    --help|-h)
        echo "OptiBus Deploy Script v4.0 — DevSecOps Production Grade"
        echo ""
        echo "Uso:"
        echo "  ./deploy.sh              Despliegue completo (pull + build + up)"
        echo "  ./deploy.sh --quick      Restart sin rebuild (actualizaciones rápidas)"
        echo "  ./deploy.sh --rollback   Revertir al último backup pre-deploy"
        echo "  ./deploy.sh --status     Ver estado de todos los servicios"
        ;;
    *)
        validate_env
        do_deploy false
        ;;
esac