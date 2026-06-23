# 🏗️ Arquitectura del Sistema

## Diagrama General

```
Internet → Caddy (80/443) → API FastAPI (8000)
                              ├── PostgreSQL + PostGIS (5432)
                              ├── Redis (6379)
                              ├── Prometheus (9090) → Grafana (3000)
                              └── WebSocket → PWA Frontend (Leaflet)
```

## Stack Tecnológico

| Capa | Tecnología | Versión |
|------|-----------|---------|
| **Proxy / SSL** | Caddy | 2.x |
| **Backend** | FastAPI (Python) | 0.136+ |
| **Base de Datos** | PostgreSQL + PostGIS | 16 + 3.4 |
| **Caché / Rate Limit** | Redis | 7.x |
| **Métricas** | Prometheus + Grafana | latest |
| **Contenedores** | Podman (rootless) | 5.x |
| **Frontend PWA** | HTML/JS/CSS vanilla + Leaflet | 1.9 |
| **APK Android** | Kotlin + OkHttp | 1.9 / 4.12 |

## Puertos

| Puerto | Servicio | Expuesto a Internet |
|--------|----------|-------------------|
| 80 | Caddy (HTTP) | ✅ Sí |
| 443 | Caddy (HTTPS) | ✅ Sí |
| 8000 | API FastAPI | ❌ Solo localhost |
| 5432 | PostgreSQL | ❌ Solo localhost |
| 6379 | Redis | ❌ Solo localhost |
| 9090 | Prometheus | ❌ Solo localhost |
| 3000 | Grafana | ❌ Solo localhost |

## Flujo de Datos

1. **APK Android** graba ruta GPS → `POST /api/routes/upload` (multipart GPX + JSON)
2. **GPS Cleaner** filtra outliers → PostGIS almacena LINESTRING + POINTs
3. **PWA** carga rutas vía `GET /api/routes` → Leaflet renderiza polilíneas + marcadores
4. **WebSocket** transmite posiciones de buses en tiempo real
5. **Caddy** sirve frontend estático + proxy inverso a API
6. **Prometheus** scrapea `/metrics` cada 15s → Grafana dashboard

## Seguridad

- **API Key** + **JWT** para endpoints de escritura
- **CORS** restringido a orígenes configurados
- **Rate Limiting** con Redis (fallback a memoria)
- **bcrypt** para hash de contraseñas (12 rounds)
- **Caddy** auto HTTPS con Let's Encrypt
- **WebSocket** con autenticación opcional (JWT/API Key)
- **X-Forwarded-For** en rate limiter (IP real detrás de proxy)
- **Bandit** escaneo SAST en CI/CD

## Estructura del Proyecto

```
OptiBus-PWA/
├── backend/
│   ├── main.py              ← API FastAPI (1425 líneas)
│   ├── models.py             ← ORM: Route, Stop, BusPosition, Driver, ApiKey
│   ├── database.py           ← Conexión asyncpg + SQLAlchemy
│   ├── ingest_gpx.py         ← Ingesta de rutas GPX
│   ├── ingest_stops.py       ← Ingesta de paradas JSON
│   ├── utils/
│   │   └── gps_cleaner.py    ← Filtro GPS (multipath, velocidad, ruido)
│   ├── tests/                ← Tests de integración (pytest-asyncio)
│   ├── Dockerfile             ← Imagen Python 3.13 (uv + no root)
│   └── requirements.txt       ← Versiones congeladas (==)
├── scripts/
│   ├── deploy.sh             ← Despliegue production-grade
│   ├── generate_env.sh       ← Generador de secretos
│   ├── seed_db.sh            ← Auto-ingesta de GPX/JSON
│   └── batch_clean_gpx.py    ← Limpieza batch de archivos GPX
├── deploy/
│   └── config/               ← Configs de Prometheus y Grafana
├── frontend/                 ← PWA estática (Caddy sirve /srv/frontend)
├── mobile-driver/            ← APK Android (Kotlin)
└── pyproject.toml            ← Config pytest + ruff + mypy
```
