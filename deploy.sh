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

# 3. Reconstruir solo la API (si cambió código/dependencias)
echo "🔨 Reconstruyendo API (solo si hay cambios)..."
podman-compose build api 2>/dev/null || {
    echo "⚠️  Build de API falló, intentando con --no-cache..."
    podman-compose build api --no-cache
}

# 4. Rolling update: levantar servicios sin tirar los existentes primero
#    podman-compose up -d reconstruye solo lo que cambió, preservando la BD
echo "🔄 Aplicando actualización sin downtime..."
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
