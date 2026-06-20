# 🗄️ Base de Datos — PostgreSQL + PostGIS

## Modelos

### Route
| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | Integer PK | Auto-incremental |
| name | String | Nombre de la ruta |
| geom | Geometry(LINESTRING, 4326) | Trayectoria GPS (índice GiST) |

### Stop
| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | Integer PK | Auto-incremental |
| name | String | Nombre de la parada |
| route_id | FK → Route | Ruta a la que pertenece |
| geom | Geometry(POINT, 4326) | Coordenada (índice GiST) |

### BusPosition
| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | Integer PK | Auto-incremental |
| bus_id | String (indexado) | Identificador del bus |
| geom | Geometry(POINT, 4326) | Posición GPS (índice GiST) |
| speed | Float | Velocidad en km/h |
| route_id | Integer | Ruta actual (opcional) |
| recorded_at | DateTime | Timestamp UTC |

### Driver
| Columna | Tipo | Descripción |
|---------|------|-------------|
| id | Integer PK | Auto-incremental |
| email | String (unique) | Email de login |
| password_hash | String | bcrypt hash |
| name | String | Nombre completo |
| bus_id | String | Bus asignado |
| role | String | "driver" o "admin" |
| is_active | Boolean | Cuenta activa |

## Índices Geoespaciales

```sql
CREATE INDEX idx_routes_geom_gist ON routes USING GIST (geom);
CREATE INDEX idx_stops_geom_gist ON stops USING GIST (geom);
CREATE INDEX idx_bus_positions_geom_gist ON bus_positions USING GIST (geom);
```

## Ingesta de Datos

### Manual
```bash
# Ruta
podman exec optibus_api python ingest_gpx.py data/ruta.gpx "Nombre Ruta"
# Paradas
podman exec optibus_api python ingest_stops.py data/paradas.json
```

### Automática (seed_db.sh)
```bash
./scripts/seed_db.sh
```

## Comandos Útiles

```bash
# Conectar a PostgreSQL
podman exec -it optibus_db psql -U optibus_admin -d optibus_prod

# Contar rutas
podman exec optibus_api python3 -c "
from database import SessionLocal
from models import Route
from sqlalchemy import select, func
import asyncio
async def main():
    async with SessionLocal() as s:
        r = await s.execute(select(func.count(Route.id)))
        print(f'Rutas: {r.scalar()}')
asyncio.run(main())"

# Backup
./scripts/backup-db.sh ./backups/

# Restaurar
./scripts/restore-db.sh ./backups/optibus_backup_20260601_020000.sql.gz