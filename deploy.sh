#!/bin/bash
# Script de Despliegue (DevSecOps) - Azure VM
# Ejecutar siempre después de un git pull

# 1. Bajar contenedores de forma segura
podman-compose down

# 2. Descargar últimas imágenes por seguridad y actualizaciones (si hay rebuild de API)
podman-compose pull
# Forza la recopilación de la API si Dockerfile/requirements han cambiado
podman-compose build api --no-cache 

# 3. Subir stack en modo rootless (detached)
podman-compose up -d

# 4. Limpieza de imágenes remanentes para no llenar el disco en Azure
podman image prune -f

echo "✅ Despliegue finalizado. Contenedores reiniciados y protegidos."
