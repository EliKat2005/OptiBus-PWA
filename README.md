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

## 🔒 Configuración de Red Segura (Android)

La app fuerza HTTPS/WSS para todas las conexiones externas. Solo permite HTTP sin cifrar en redes locales (192.168.x.x, 10.x.x.x, localhost) para desarrollo.

## Comandos Adicionales Útiles

- Revisar los logs en tiempo real o trackear WebSockets: `podman logs -f optibus_api`
- Verificar health de la API: `curl -s http://localhost:8000/health | jq`
- Acceder a la BD directamente: `podman exec -it optibus_db psql -U optibus_admin -d optibus_prod`
- Apagar todos los servicios manualmente: `podman-compose down`
- Tumbar todo *destruyendo* el volumen de base de datos (Pelígrosamente destructivo): `podman-compose down -v`
