# OptiBus 🚌

OptiBus es una aplicación web del tipo Progressive Web App (PWA) diseñada para rastrear y reportar la ubicación de autobuses en tiempo real sobre rutas y paradas geolocalizadas.

## Arquitectura del Proyecto

El sistema está dividido en:
- **Backend**: API REST en Python (FastAPI) con WebSockets para transmisión de la ubicación en tiempo real.
- **Base de Datos**: PostgreSQL + PostGIS, especializada en almacenamiento geoespacial.
- **Frontend**: HTML/JS/CSS vanilla (Aplicación Web estática), servida mediante Caddy.
- **Infraestructura**: Despliegue orquestado 100% con Docker Compose / Podman Compose.

## Requisitos Previos

- Tener instalado [Docker](https://docs.docker.com/get-docker/) y Docker Compose, o bien [Podman](https://podman.io/) y Podman Compose.
- Puertos `8080`, `8000` y `5432` disponibles localmente.

## Guía de Arranque (Local)

Sigue estos pasos cuidadosamente para levantar el proyecto tras haberlo clonado:

### 1. Construir y Levantar los Contenedores
En la raíz del proyecto, ejecuta (utiliza `podman` si empleas Podman en lugar de Docker):

```bash
docker compose up --build -d
```

### 2. Poblar la Base de Datos (Ingesta Inicial)
> **⚠️ IMPORTANTE:** El orden de ingesta es estricto. Las paradas dependen de que su ruta exista primero en la base de datos debido a las dependencias de Llave Foránea (Foreign Key).

**Primero**, ingesta la ruta estructurada desde el archivo GPX:
```bash
docker exec -it optibus_api python ingest_gpx.py data/ruta_ejemplo.gpx "Ruta Principal"
```

**Segundo**, ingesta las paradas del sistema:
```bash
docker exec -it optibus_api python ingest_stops.py data/paradas_ejemplo.json
```

### 3. Accesos y Enlaces

Una vez levantado todo y habiendo inyectado los datos, puedes acceder a:
- **Mapa y Usuario Central:** [http://localhost:8080](http://localhost:8080)
- **Panel del Conductor:** [http://localhost:8080/driver.html](http://localhost:8080/driver.html)
- **Documentación API (Swagger/OpenAPI):** [http://localhost:8000/docs](http://localhost:8000/docs)

## Estructura del Repositorio

- `backend/`: Código de FastAPI, conexión a DB espacial y modelos de base de datos.
- `backend/data/`: Archivos semilla (.json y .gpx) de ejemplo para la ingesta de datos base.
- `frontend/`: Código fuente de las interfaces de usuario.
- `Caddyfile`: Configuración del servidor proxy Caddy.
- `compose.yaml`: Declaración de la infraestructura dockerizada.

## Comandos Adicionales Útiles

- Ver los logs del backend en vivo: `docker compose logs -f api`
- Apagar todos los servicios: `docker compose down`
- Apagar todos los servicios y **borrar** el volumen de base de datos (Reset): `docker compose down -v`
