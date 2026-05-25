import sys
import asyncio
import gpxpy
from database import SessionLocal
from models import Route

async def ingest_gpx(file_path: str, route_name: str):
    print(f"Leyendo archivo GPX: {file_path}")
    try:
        with open(file_path, 'r') as gpx_file:
            gpx = gpxpy.parse(gpx_file)
    except Exception as e:
        print(f"Error al leer el archivo GPX: {e}")
        return
    
    points = []
    # GPX organiza los datos frecuentemente en Tracks -> Segments -> Points
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                # WKT LINESTRING requiere orden: Longitud Latitud (X Y)
                points.append(f"{point.longitude} {point.latitude}")
                
    if not points:
        print("No se encontraron puntos en el archivo GPX.")
        return

    # Construimos la geometría usando EWKT (Extended Well-Known Text)
    # Incluye el SRID para que PostGIS sepa el sistema de coordenadas.
    linestring_wkt = f"SRID=4326;LINESTRING({', '.join(points)})"
    
    async with SessionLocal() as session:
        try:
            new_route = Route(name=route_name, geom=linestring_wkt)
            session.add(new_route)
            await session.commit()
            print(f"¡Éxito! Ruta '{route_name}' insertada con {len(points)} puntos topográficos georreferenciados.")
        except Exception as e:
            await session.rollback()
            print(f"Error al insertar en la base de datos: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Uso: python ingest_gpx.py <ruta_al_archivo.gpx> <nombre_de_la_ruta>")
        sys.exit(1)
    
    gpx_path = sys.argv[1]
    name = sys.argv[2]
    
    # DevSecOps: Validar sanitización del nombre de ruta y del archivo
    if not os.path.isfile(gpx_path):
        print(f"Error: El archivo '{gpx_path}' no existe o no es accesible.")
        sys.exit(1)
    
    # Validar extensión .gpx
    if not gpx_path.lower().endswith('.gpx'):
        print("Advertencia: El archivo no tiene extensión .gpx. ¿Estás seguro de que es un GPX válido?")
    
    # Sanitizar nombre de ruta: solo permitir caracteres seguros
    import re
    safe_name = re.sub(r'[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ _\-]', '', name).strip()
    if not safe_name:
        print("Error: El nombre de la ruta contiene caracteres no permitidos o está vacío.")
        sys.exit(1)
    if safe_name != name:
        print(f"Nombre sanitizado: '{name}' -> '{safe_name}'")
    
    asyncio.run(ingest_gpx(gpx_path, safe_name))
