# OptiBus 🚌

OptiBus es una aplicación web del tipo Progressive Web App (PWA) diseñada para rastrear y reportar la ubicación de autobuses en tiempo real sobre rutas y paradas geolocalizadas.

## Arquitectura del Proyecto

El sistema está dividido en:
- **Backend**: API REST en Python (FastAPI) con WebSockets para transmisión de la ubicación en tiempo real.
- **Base de Datos**: PostgreSQL + PostGIS, especializada en almacenamiento geoespacial.
- **Frontend**: HTML/JS/CSS vanilla (Aplicación Web estática), servida mediante Caddy.
- **Infraestructura**: Despliegue orquestado 100% con Docker Compose / Podman Compose.

## Requisitos Previos

- Tener instalado [Podman](https://podman.io/) y `podman-compose` (Recomendado bajo arquitecturas rootless/DevSecOps) o bien Docker.
- Git instalado en tu máquina o servidor.
- Puertos `80` (HTTP) y `443` (HTTPS) disponibles en tu firewall (NSG en Azure).

## 🚀 Despliegue en Producción (Servidor Azure VM / VPS)

OptiBus está diseñado bajo una arquitectura **DevSecOps** segura. Nuestro proxy Caddy se encarga de aislar la capa interna y generar tus certificados SSL dinámicamente usando tu dominio.

### 1. Clonar y Configurar Entorno
Entra a tu servidor virtual vía SSH y clona el proyecto:

```bash
git clone https://github.com/TU_USUARIO/OptiBus-PWA.git
cd OptiBus-PWA
```

Genera tu archivo de configuración seguro a partir de la plantilla y edítalo:
```bash
cp .env.example .env
nano .env
```
> **⚠️ Importante**: Asegúrate de cambiar la variable `DOMAIN` por tu dominio real (Ej. `app.mi-dominio.com`) y colocar una contraseña fuerte en `POSTGRES_PASSWORD`.

### 2. Despliegue Automatizado
Asegúrate de haber apuntado el Récord 'A' de tu dominio a la IP pública de tu Azure VM. Luego, corre el script de despliegue principal:

```bash
./deploy.sh
```

### 3. Poblar la Base de Datos (Primer Arránque)
> El orden de ingesta es estricto. Las paradas dependen de la existencia de una ruta por las relaciones de Foreign Key en la DDBB espacia.

**Primero**, ingiere la ruta estructurada:
```bash
podman exec -it optibus_api python ingest_gpx.py data/ruta_ejemplo.gpx "Ruta Principal"
```

**Segundo**, ingiere las paradas del sistema:
```bash
podman exec -it optibus_api python ingest_stops.py data/paradas_ejemplo.json
```

Una vez completado de levantar todo, tu plataforma PWA en vivo está en **https://tulink.com**.


## 🔄 Actualizaciones y Mantenimiento Continúo (CI/CD Local)

Como la base de código ha sido tratada a fondo, enviar actualizaciones a producción es sumamente sencillo. 
Para actualizar tu plataforma con el código nuevo subido desde Github (commits), simplemente accede a la VM por SSH, colócate en la carpeta del repositorio y ejecuta:

```bash
git pull origin main
./deploy.sh
```
El script `./deploy.sh` **reconstruirá automáticamente** las partes modificadas sin tocar ni corromper tu base de datos persistente. Caddy renovará los puertos y limpiará imágenes huérfanas automáticamente de la VM para ahorrar costos.

## Estructura del Repositorio

- `backend/`: Código de FastAPI, conexión a DB espacial y modelos de base de datos.
- `backend/data/`: Archivos semilla (.json y .gpx) de ejemplo para la ingesta de datos base.
- `frontend/`: Código fuente de las interfaces de usuario web PWA y offline caching Service Worker.
- `mobile-driver/`: Aplicación Kotlin nativa Android, interactiva por WebSocket seguro al backend.
- `Caddyfile`: Configuración CSP reforzada del servidor proxy + auto HTTPS.
- `compose.yaml`: Declaración de la infraestructura dockerizada aislada.
- `deploy.sh`: Script de mantenimiento ágil DevSecOps y auto-levantamiento.

## 🔐 Seguridad: Configurar API Key para Endpoints GPS

Para proteger los endpoints de escritura GPS (`/api/gps/update`, `/api/gps/owntracks`), define una API Key en tu `.env`:

```bash
# Genera una key segura en tu VM:
openssl rand -base64 32
# Copia el resultado y pégalo en .env:
OPTIBUS_API_KEY=TU_KEY_GENERADA
```

> Si `OPTIBUS_API_KEY` no se define, los endpoints funcionan sin autenticación (retrocompatible con despliegues existentes). En producción, **siempre define esta variable**.

Para que la app Android use la API Key, ingresa la misma key en el campo `api_key` de SharedPreferences o configúrala programáticamente.

## 💾 Backup Automático de Base de Datos

El script `scripts/backup-db.sh` realiza backups comprimidos de PostgreSQL/PostGIS. Para programarlo diariamente:

```bash
# En la VM de Azure, agrega al crontab:
crontab -e
# Agrega esta línea (backup diario a las 2:00 AM):
0 2 * * * /home/tu_usuario/OptiBus-PWA/scripts/backup-db.sh /home/tu_usuario/backups
```

Para restaurar un backup:
```bash
./scripts/restore-db.sh ./backups/optibus_backup_20250101_020000.sql.gz
```

## 📱 App Android: Configuración Segura del Keystore

Las credenciales del keystore ya no se almacenan en `build.gradle.kts`. Para firmar el APK:

```bash
cd mobile-driver
cp keystore.properties.template keystore.properties
nano keystore.properties  # Configura tus credenciales reales
```

El archivo `keystore.properties` está en `.gitignore` y nunca se sube al repositorio.

## 📊 Dashboard de Administración

Accede al panel de control en `https://tudominio.com/admin` para ver:
- Buses activos en tiempo real
- Estado de conexiones WebSocket
- Métricas de sistema (DB, Redis, versión)
- Tabla de buses con última posición y velocidad

## 🧭 Geocerca y Alertas de Desvío

Verifica si un bus está dentro de la ruta:
```bash
curl "https://tudominio.com/api/alert/geofence?bus_id=Bus-1&lat=0.35&lon=-78.12&max_distance_meters=200"
```

## ⏱️ ETA - Tiempo Estimado de Llegada

Calcula cuánto tardará un bus en llegar a una parada:
```bash
curl "https://tudominio.com/api/eta?bus_id=Bus-1&stop_id=1"
```

## 🗺️ Soporte Multi-Ruta

El simulador ahora soporta múltiples rutas simultáneamente. Si tienes más de una ruta en la base de datos, se crearán buses para cada una.

## 📡 Monitoreo con Prometheus + Grafana

Métricas disponibles en `/metrics` (Prometheus). Grafana accesible en `http://localhost:3000` (solo desde la VM).

```bash
# Ver métricas
curl http://localhost:8000/metrics

# Acceder a Grafana (requiere tunnel SSH o VPN)
# Usuario: admin / Contraseña: la definida en .env (GRAFANA_PASSWORD)
```

## 🔒 Configuración de Red Segura (Android)

La app fuerza HTTPS/WSS para todas las conexiones externas. Solo permite HTTP sin cifrar en redes locales (192.168.x.x, 10.x.x.x, localhost) para desarrollo.

## 🧪 Tests Automatizados

Ejecutar tests localmente:
```bash
cd backend
pip install pytest pytest-asyncio httpx
python -m pytest test_api.py -v
```

CI/CD con GitHub Actions: cada push a `main` ejecuta tests, linters y análisis de seguridad (Bandit + ShellCheck).

## 🚀 Actualizar desde la VM de Azure

```bash
ssh azureuser@<ip-vm>
cd ~/OptiBus-PWA
git pull origin main

# Si es la primera vez con esta versión, actualiza .env:
# nano .env
# Agrega: REDIS_URL=redis://redis:6379/0
#         GRAFANA_PASSWORD=<tu_password_seguro>
#         API_REPLICAS=2

./deploy.sh
```

> **Nota**: El primer despliegue después de esta actualización tomará ~2-3 minutos extra porque se descarga Redis, Prometheus y Grafana.

## 📋 Endpoints Nuevos (v0.4.0)

| Endpoint | Descripción |
|---|---|
| `GET /admin` | Dashboard HTML administrativo |
| `GET /api/bus/active` | Lista buses activos |
| `GET /api/bus/history?bus_id=X&minutes=30` | Historial de posiciones |
| `GET /api/alert/geofence?bus_id=X&lat=Y&lon=Z` | Verificar desvío de ruta |
| `GET /api/eta?bus_id=X&stop_id=Y` | Tiempo estimado de llegada |
| `GET /api/simulator/status` | Estado del simulador |
| `GET /api/auth/status` | Estado de API Key |
| `GET /metrics` | Métricas Prometheus |

## Comandos Adicionales Útiles

- Revisar logs API: `podman logs -f optibus_api`
- Verificar health: `curl -s http://localhost:8000/health`
- Métricas Prometheus: `curl -s http://localhost:8000/metrics`
- Acceder a BD: `podman exec -it optibus_db psql -U optibus_admin -d optibus_prod`
- Conectar a Redis: `podman exec -it optibus_redis redis-cli`
- Ver réplicas activas: `podman ps --filter name=optibus_api`
- Dashboard admin: `https://tudominio.com/admin`
- Apagar servicios: `podman-compose down`
- Destruir todo (⚠️): `podman-compose down -v`
