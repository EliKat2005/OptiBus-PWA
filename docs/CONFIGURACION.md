# Configuración de OptiBus

## Variables de Entorno

Crear un archivo `.env` en la raíz del proyecto copiando desde `.env.example`:

```bash
cp .env.example .env
nano .env
```

### Variables requeridas

| Variable | Ejemplo | Descripción |
|----------|---------|-------------|
| `POSTGRES_DB` | `optibus_prod` | Nombre de la base de datos |
| `POSTGRES_USER` | `optibus_admin` | Usuario de PostgreSQL |
| `POSTGRES_PASSWORD` | `(generar segura)` | Contraseña de PostgreSQL — NUNCA usar el default |
| `POSTGRES_HOST` | `db` | Hostname del contenedor DB (no cambiar) |
| `POSTGRES_PORT` | `5432` | Puerto PostgreSQL |
| `DOMAIN` | `ecae.me` | Dominio público para SSL automático con Caddy |
| `OPTIBUS_API_KEY` | `(openssl rand -base64 32)` | API Key para autenticación — mín. 16 caracteres |
| `REDIS_PASSWORD` | `(valor seguro)` | Contraseña de Redis |
| `REDIS_URL` | `redis://:PASSWORD@redis:6379/0` | URL de conexión Redis con contraseña |
| `CORS_ORIGINS` | `https://tudominio.com,http://localhost` | Orígenes permitidos para CORS |
| `GRAFANA_USER` | `admin` | Usuario admin de Grafana |
| `GRAFANA_PASSWORD` | `(valor seguro)` | Contraseña de Grafana — NUNCA usar `admin` |

### Variables opcionales

| Variable | Default | Descripción |
|----------|---------|-------------|
| `ENABLE_BUS_SIMULATOR` | `false` | Activar simulación de buses (solo desarrollo) |
| `LOG_LEVEL` | `INFO` | Nivel de logging: DEBUG, INFO, WARNING, ERROR |
| `API_REPLICAS` | `2` | Número de réplicas de API (requiere orquestador) |

## Seguridad

- **NUNCA** subir el archivo `.env` al repositorio (está en `.gitignore`)
- Usar contraseñas fuertes y únicas para cada entorno
- En producción, Caddy genera certificados SSL automáticamente vía Let's Encrypt
- Rotar credenciales periódicamente
- El archivo `keystore.properties` del APK Android tampoco se versiona
- Las API Keys usan comparación timing-safe (`compare_digest`)

## Monitoreo

- **Prometheus**: accesible solo desde localhost en `http://localhost:9090`
- **Grafana**: accesible solo desde localhost en `http://localhost:3000`
- Para acceder remotamente, usar SSH tunnel:
  ```bash
  ssh -L 3000:localhost:3000 azureuser@<ip-vm>
  # Abrir http://localhost:3000 en el navegador
  ```

## Red interna

Los servicios se comunican a través de la red Docker `backend_net`:
- `api` → `db:5432` (PostgreSQL + PostGIS)
- `api` → `redis:6379` (Redis con requirepass)
- `web` (Caddy) → `api:8000` (API backend)
- `prometheus` → `api:8000/metrics` (scrape de métricas)

## Despliegue

```bash
# Primer despliegue
./deploy.sh

# Actualización rápida (sin rebuild)
./deploy.sh --quick

# Rollback al backup anterior
./deploy.sh --rollback

# Ver estado de servicios
./deploy.sh --status
```

## Backup y Restauración

```bash
# Backup manual
./scripts/backup-db.sh ./backups

# Backup automático (crontab)
# 0 2 * * * /home/azureuser/OptiBus-PWA/scripts/backup-db.sh /home/azureuser/backups

# Restauración
./scripts/restore-db.sh ./backups/optibus_backup_20250101_020000.sql.gz