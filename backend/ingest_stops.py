import asyncio
import json
import sys

from database import SessionLocal
from models import Route, Stop
from sqlalchemy import select


async def ingest_stops(file_path: str, route_id: int | None = None):
    print(f"Leyendo archivo de paradas: {file_path}")
    try:
        with open(file_path) as f:
            stops_data = json.load(f)
    except Exception as e:
        print(f"Error al leer el archivo JSON: {e}")
        return

    async with SessionLocal() as session:
        try:
            # Si no se especifica route_id, usar el último route_id en la BD
            if route_id is None:
                # Intentar obtener de la primera parada (formato viejo)
                if stops_data and "route_id" in stops_data[0]:
                    route_id = stops_data[0]["route_id"]
                else:
                    # Buscar la última ruta activa
                    result = await session.execute(
                        select(Route.id).order_by(Route.id.desc()).limit(1)
                    )
                    row = result.scalar()
                    if row:
                        route_id = row
                        print(f"Usando route_id={route_id} (última ruta en BD)")
                    else:
                        print("Error: No hay rutas en la BD. Ingiere una ruta primero.")
                        return

            count = 0
            for stop in stops_data:
                if "lat" not in stop or "lon" not in stop:
                    print(f"Advertencia: parada sin coordenadas, omitiendo: {stop}")
                    continue
                # WKT POINT requiere orden: Longitud Latitud (X Y)
                point_wkt = f"SRID=4326;POINT({stop['lon']} {stop['lat']})"

                new_stop = Stop(
                    name=stop.get("name", f"Parada {count+1}"),
                    route_id=route_id,
                    geom=point_wkt
                )
                session.add(new_stop)
                count += 1

            await session.commit()
            print(f"¡Éxito! {count} paradas insertadas en PostGIS (route_id={route_id}).")
        except Exception as e:
            await session.rollback()
            print(f"Error al insertar en la base de datos: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python ingest_stops.py <archivo_paradas.json> [route_id]")
        print("  Si no se especifica route_id, se usa el de la primera parada o la última ruta en BD.")
        sys.exit(1)

    json_path = sys.argv[1]
    rid = int(sys.argv[2]) if len(sys.argv) > 2 else None
    asyncio.run(ingest_stops(json_path, rid))
