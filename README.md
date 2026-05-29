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

## Comandos Adicionales Útiles

- Revisar los logs en tiempo real o trackear WebSockets: `podman logs -f optibus_api`
- Apagar todos los servicios manualmente: `podman-compose down`
- Tumbar todo *destruyendo* el volumen de base de datos (Pelígrosamente destructivo): `podman-compose down -v`
