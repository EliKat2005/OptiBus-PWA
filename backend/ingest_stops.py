import sys
import asyncio
import json
from database import SessionLocal
from models import Stop

async def ingest_stops(file_path: str):
    print(f"Leyendo archivo de paradas: {file_path}")
    try:
        with open(file_path, 'r') as f:
            stops_data = json.load(f)
    except Exception as e:
        print(f"Error al leer el archivo JSON: {e}")
        return
    
    async with SessionLocal() as session:
        try:
            count = 0
            for stop in stops_data:
                # WKT POINT requiere orden: Longitud Latitud (X Y)
                point_wkt = f"SRID=4326;POINT({stop['lon']} {stop['lat']})"
                
                new_stop = Stop(
                    name=stop["name"],
                    route_id=stop["route_id"],
                    geom=point_wkt
                )
                session.add(new_stop)
                count += 1
                
            await session.commit()
            print(f"¡Éxito! {count} paradas insertadas en PostGIS.")
        except Exception as e:
            await session.rollback()
            print(f"Error al insertar en la base de datos: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Uso: python ingest_stops.py <archivo_paradas.json>")
        sys.exit(1)
    
    json_path = sys.argv[1]
    asyncio.run(ingest_stops(json_path))