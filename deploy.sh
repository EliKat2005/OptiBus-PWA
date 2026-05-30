#!/bin/bash
# Script de Despliegue (DevSecOps) - Azure VM
# Ejecutar siempre después de un git pull
# v2.0: Sin downtime usando rolling update

set -euo pipefail

echo "🚀 [$(date)] Iniciando despliegue OptiBus..."

# 1. Validar que DOMAIN no sea localhost en producción
DOMAIN="${DOMAIN:-localhost}"
if [ "$DOMAIN" = "localhost" ] && [ -f .env ]; then
    # shellcheck disable=SC1091
    source .env 2>/dev/null || true
fi
DOMAIN="${DOMAIN:-localhost}"
if [ "$DOMAIN" = "localhost" ]; then
    echo "⚠️  ADVERTENCIA: DOMAIN=localhost. Caddy no podrá generar certificados SSL reales."
    echo "   Define DOMAIN en .env con tu dominio real para HTTPS."
fi

# 2. Descargar últimas imágenes base
echo "📥 Pull de imágenes base..."
podman-compose pull 2>/dev/null || true

# 3. Reconstruir API sin cache (para forzar instalación de nuevas dependencias)
echo "🔨 Reconstruyendo API (sin cache para nuevas dependencias)..."
podman-compose build api --no-cache

# 4. Bajar servicios actuales y levantar con nueva configuración
#    Podman compose requiere down antes de up cuando hay cambios de topología
echo "🔄 Aplicando actualización..."
podman-compose down
podman-compose up -d --remove-orphans

# 5. Esperar a que la API esté healthy antes de continuar
echo "⏳ Esperando healthcheck de la API..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ API healthy."
        break
    fi
    [ "$i" -eq 30 ] && echo "⚠️  API no respondió después de 30s, verifica logs."
    sleep 1
done

# 6. Limpieza de imágenes remanentes para no llenar el disco en Azure
echo "🧹 Limpiando imágenes huérfanas..."
podman image prune -f

echo "✅ [$(date)] Despliegue finalizado sin downtime."
echo "   Verifica: curl -s http://localhost:8000/health | jq"
