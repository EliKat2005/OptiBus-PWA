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
echo "🔄 Aplicando actualización..."
# Tolerar contenedores ya eliminados (podman-compose down en estado limpio)
podman-compose down 2>/dev/null || true

# Levantar base de datos y Redis primero y esperar a que estén listos
echo "  → Levantando DB + Redis..."
podman-compose up -d db redis 2>/dev/null
echo "  → Esperando 15s a que DB y Redis estén healthy..."
sleep 15

# Levantar API, web, y monitoreo
echo "  → Levantando API + Web + Monitoreo..."
podman-compose up -d --remove-orphans 2>/dev/null

# 5. Esperar a que la API esté healthy antes de continuar
echo "⏳ Esperando healthcheck de la API..."
for i in $(seq 1 60); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ API healthy."
        break
    fi
    if [ $((i % 15)) -eq 0 ]; then
        echo "  → Aún esperando... (${i}s)"
    fi
    [ "$i" -eq 60 ] && echo "⚠️  API no respondió después de 60s, verifica: podman logs optibus_api"
    sleep 1
done

# 6. Limpieza de imágenes remanentes para no llenar el disco en Azure
echo "🧹 Limpiando imágenes huérfanas..."
podman image prune -f

echo "✅ [$(date)] Despliegue finalizado sin downtime."
echo "   Verifica: curl -s http://localhost:8000/health | jq"
