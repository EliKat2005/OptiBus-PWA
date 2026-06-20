# 📚 OptiBus — Documentación Técnica

Bienvenido a la Wiki técnica de OptiBus. Aquí encontrarás toda la información necesaria para entender, desplegar y mantener el proyecto.

## 🗂️ Índice

| Archivo | Contenido |
|---------|-----------|
| [`architecture.md`](architecture.md) | Arquitectura del sistema, stack tecnológico y puertos |
| [`api-reference.md`](api-reference.md) | Endpoints REST, WebSocket, autenticación y ejemplos curl |
| [`deployment.md`](deployment.md) | Cold Start, scripts de aprovisionamiento y deploy |
| [`database.md`](database.md) | Modelos de datos, PostGIS, ingestas y backups |
| [`mobile-app.md`](mobile-app.md) | APK Android, compilación con Podman y configuración |
| [`development.md`](development.md) | Setup local, tests, CI/CD y herramientas |
| [`troubleshooting.md`](troubleshooting.md) | Errores comunes y soluciones rápidas |

## 🎯 Notion Simplificado — Kanban Unificado

| Columna | Contenido |
|---------|-----------|
| 📋 Backlog | Features pendientes |
| 🚧 In Progress | Desarrollo actual |
| ✅ Done | Commits completados |
| 🐛 Bugs | Incidencias activas |

**Etiquetas**: `#feature` `#bug` `#backend` `#frontend` `#apk` `#infra` `#docs`

> **Stack**: FastAPI + PostGIS + Redis + Caddy + Prometheus + Grafana + Podman + Leaflet + PWA + Kotlin Android