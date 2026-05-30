#!/bin/bash
# OptiBus Deploy Script - DevSecOps
# v3.0: Simplificado, robusto, sin bloqueos
set -euo pipefail

echo "🚀 [$(date)] Iniciando despliegue OptiBus..."

# 0. Validar .env y DOMAIN
if [ -f .env ]; then source .env 2>/dev/null || true; fi
if [ "${DOMAIN:-localhost}" = "localhost" ]; then
    echo "⚠️  DOMAIN=localhost. Solo HTTP sin SSL real."
fi

# 1. Pull de imágenes base (redis, postgis, caddy, etc.)
echo "📥 Pull de imágenes base..."
podman-compose pull 2>/dev/null || true

# 2. Reconstruir la API (sin cache = dependencias frescas)
echo "🔨 Build de API..."
podman-compose build api --no-cache

# 3. Bajar todo y levantar limpio
echo "🔄 Reiniciando servicios..."
podman-compose down 2>/dev/null || true
podman-compose up -d

# 4. Esperar health de la API (hasta 90s)
echo "⏳ Esperando health de la API..."
for i in $(seq 1 90); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "✅ API healthy ($(curl -s http://localhost:8000/health))"
        break
    fi
    [ $((i % 10)) -eq 0 ] && echo "   ... ${i}s"
    [ "$i" -eq 90 ] && { echo "❌ API no respondió. Logs:"; podman logs optibus_api --tail 20; exit 1; }
    sleep 1
done

# 5. Limpieza
echo "🧹 Limpiando imágenes huérfanas..."
podman image prune -f

echo "✅ Despliegue completado."