#!/usr/bin/env python3
"""
ingest_gpx.py - OptiBus DevSecOps
==================================
Inhiere rutas GPX en PostGIS con limpieza automática de GPS integrada.

Uso:
    python ingest_gpx.py <ruta.gpx> <"Nombre de Ruta">
    python ingest_gpx.py <ruta.gpx> <"Nombre de Ruta"> --no-clean
    python ingest_gpx.py <ruta.gpx> <"Nombre de Ruta"> --in-place

Pipeline automático:
    1. Lee el archivo GPX
    2. Extrae puntos GPS crudos (lat, lon, timestamp)
    3. APLICA LIMPIEZA automática: multipath, velocidad, ruido estático, suavizado
    4. Construye LINESTRING WKT con los puntos limpios
    5. Inserta en PostGIS

Flags:
    --no-clean    Deshabilita la limpieza automática
    --in-place    Sobrescribe el archivo .gpx original con la versión limpiada
"""

import argparse
import asyncio
import logging
import os
import re
import sys
from pathlib import Path

import gpxpy
from database import SessionLocal
from models import Route
from utils.gps_cleaner import clean_gps_track_with_stats

# ────────────────────────────────────────────────
# Configuración de logging
# ────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("ingest-gpx")


# ────────────────────────────────────────────────
# Función principal de ingesta
# ────────────────────────────────────────────────

async def ingest_gpx(
    file_path: str,
    route_name: str,
    clean: bool = True,
    in_place: bool = False,
    max_speed_kmh: float = 80.0,
    min_distance_m: float = 2.0,
    smooth_window: int = 5,
) -> bool:
    """
    Inhiere una ruta GPX en PostGIS con limpieza automática opcional.

    Args:
        file_path: Ruta al archivo .gpx.
        route_name: Nombre de la ruta en la base de datos.
        clean: Si es True, aplica limpieza GPS antes de insertar.
        in_place: Si es True y clean=True, sobrescribe el archivo original
                  con la versión limpiada.
        max_speed_kmh: Velocidad máxima permitida en km/h.
        min_distance_m: Distancia mínima entre puntos en metros.
        smooth_window: Ventana de suavizado (debe ser impar).

    Returns:
        True si la ingesta fue exitosa, False en caso contrario.
    """
    logger.info(f"🚌 Ingiriendo ruta: '{route_name}' desde {file_path}")
    logger.info(f"   Limpieza: {'✅ Activada' if clean else '❌ Desactivada'}")
    if clean:
        logger.info(
            f"   Parámetros: vel máx={max_speed_kmh:.0f} km/h, "
            f"dist mín={min_distance_m:.1f}m, suavizado={smooth_window}"
        )

    # ── 1. Leer archivo GPX ──
    try:
        with open(file_path, encoding='utf-8') as gpx_file:
            gpx = gpxpy.parse(gpx_file)
    except Exception as e:
        logger.error(f"Error al leer el archivo GPX: {e}")
        return False

    # ── 2. Extraer puntos crudos ──
    raw_points: list[tuple[float, float, str]] = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                if point.time:
                    iso_time = point.time.strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    iso_time = ""
                raw_points.append((point.latitude, point.longitude, iso_time))

    raw_count = len(raw_points)
    logger.info(f"   Puntos crudos extraídos: {raw_count}")

    if raw_count < 2:
        logger.error("Se requieren al menos 2 puntos GPS para una ruta.")
        return False

    # ── 3. Limpieza automática (si está activada) ──
    if clean:
        result = clean_gps_track_with_stats(
            raw_points,
            max_speed_kmh=max_speed_kmh,
            min_distance_m=min_distance_m,
            smooth_window=smooth_window,
        )
        cleaned_points = result.points
        logger.info(
            f"   ✅ Limpieza completada: {raw_count} → {len(cleaned_points)} puntos "
            f"({result.stats['porcentaje_eliminado']}% eliminado)"
        )
        logger.info(
            f"      └─ {result.stats['multipath_ghosts']} ghost/multipath, "
            f"{result.stats['velocidad_excesiva']} velocidad, "
            f"{result.stats['ruido_estatico']} ruido estático, "
            f"{result.stats['duplicados']} duplicados"
        )

        # Guardar versión limpiada in-place si se solicita
        if in_place and len(cleaned_points) >= 2:
            try:
                from batch_clean_gpx import build_clean_gpx_from_points
                clean_xml = build_clean_gpx_from_points(
                    cleaned_points,
                    name=gpx.name or route_name,
                    description=getattr(gpx, 'description', '') or f"Ruta limpiada automáticamente - {route_name}",
                    creator="OptiBus GPS Cleaner (DevSecOps)",
                )
                # Backup del original con sufijo .bak
                backup_path = Path(file_path).with_suffix('.gpx.bak')
                os.rename(file_path, str(backup_path))
                with open(file_path, 'w', encoding='utf-8') as f:
                    f.write(clean_xml)
                logger.info(f"   💾 Archivo original respaldado como: {backup_path.name}")
                logger.info(f"   📝 Archivo .gpx sobrescrito con versión limpiada ({len(cleaned_points)} pts)")
            except Exception as e:
                logger.warning(f"   ⚠️ No se pudo sobrescribir el archivo in-place: {e}")
    else:
        cleaned_points = raw_points

    if len(cleaned_points) < 2:
        logger.error("Después de la limpieza quedaron menos de 2 puntos. Abortando ingesta.")
        return False

    # ── 4. Construir LINESTRING WKT ──
    # Las rutas SIN limpieza usan (lon, lat) directo; las limpias son (lat, lon, ts)
    # así que adaptamos según el tipo
    if clean:
        # cleaned_points es List[(lat, lon, iso_time)]
        wkt_coords = [f"{lon} {lat}" for lat, lon, _ in cleaned_points]
    else:
        # raw_points es List[(lat, lon, iso_time)]
        wkt_coords = [f"{lon} {lat}" for lat, lon, _ in cleaned_points]

    linestring_wkt = f"SRID=4326;LINESTRING({', '.join(wkt_coords)})"

    # ── 5. Insertar en PostGIS ──
    async with SessionLocal() as session:
        try:
            new_route = Route(name=route_name, geom=linestring_wkt)
            session.add(new_route)
            await session.commit()
            await session.refresh(new_route)
            logger.info(
                f"   🗺️  ¡Ruta '{route_name}' (ID={new_route.id}) insertada "
                f"con {len(wkt_coords)} puntos!"
            )
            return True
        except Exception as e:
            await session.rollback()
            logger.error(f"   ❌ Error al insertar en la base de datos: {e}")
            return False


# ────────────────────────────────────────────────
# CLI
# ────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="OptiBus GPX Ingest - DevSecOps con limpieza automática",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Ejemplos:
  # Ingesta estándar con limpieza automática:
  python ingest_gpx.py data/ruta.gpx "Ruta Centro-Norte"

  # Ingesta sin limpieza (datos ya validados):
  python ingest_gpx.py data/ruta.gpx "Ruta Centro-Norte" --no-clean

  # Ingesta + sobrescribir archivo original con versión limpia:
  python ingest_gpx.py data/ruta.gpx "Ruta Centro-Norte" --in-place

  # Ajustar parámetros de limpieza:
  python ingest_gpx.py data/ruta.gpx "Ruta Centro-Norte" --speed 60 --distance 3
        """,
    )

    parser.add_argument("gpx_path", help="Ruta al archivo .gpx")
    parser.add_argument("route_name", help="Nombre de la ruta en la BD")
    parser.add_argument(
        "--no-clean",
        action="store_true",
        help="Deshabilita la limpieza automática de GPS",
    )
    parser.add_argument(
        "--in-place",
        action="store_true",
        help="Sobrescribe el archivo .gpx original con la versión limpiada "
             "(crea backup .gpx.bak)",
    )
    parser.add_argument(
        "--speed",
        type=float,
        default=80.0,
        help="Velocidad máxima en km/h (default: 80)",
    )
    parser.add_argument(
        "--distance",
        type=float,
        default=2.0,
        help="Distancia mínima entre puntos en metros (default: 2.0)",
    )
    parser.add_argument(
        "--smooth",
        type=int,
        default=5,
        help="Ventana de suavizado, debe ser impar (default: 5)",
    )

    args = parser.parse_args()

    # Validaciones DevSecOps
    if not os.path.isfile(args.gpx_path):
        logger.error(f"El archivo '{args.gpx_path}' no existe o no es accesible.")
        sys.exit(1)

    if not args.gpx_path.lower().endswith('.gpx'):
        logger.warning(
            "El archivo no tiene extensión .gpx. ¿Estás seguro de que es un GPX válido?"
        )

    # Sanitizar nombre de ruta
    safe_name = re.sub(
        r'[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ _\-]',
        '',
        args.route_name
    ).strip()

    if not safe_name:
        logger.error(
            "El nombre de la ruta contiene caracteres no permitidos o está vacío."
        )
        sys.exit(1)

    if safe_name != args.route_name:
        logger.info(f"Nombre sanitizado: '{args.route_name}' → '{safe_name}'")

    # Validar ventana de suavizado
    if args.smooth % 2 == 0:
        logger.error("La ventana de suavizado debe ser impar")
        sys.exit(1)

    success = asyncio.run(ingest_gpx(
        file_path=args.gpx_path,
        route_name=safe_name,
        clean=not args.no_clean,
        in_place=args.in_place,
        max_speed_kmh=args.speed,
        min_distance_m=args.distance,
        smooth_window=args.smooth,
    ))

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
