#!/usr/bin/env python3
"""
Batch GPX Cleaner - OptiBus DevSecOps
======================================
Procesa todos los archivos .gpx en backend/data/ (excepto los ya limpiados
con sufijo _cleaned.gpx) y genera versiones normalizadas _cleaned.gpx.

Uso:
    python batch_clean_gpx.py                    # Procesar todo data/
    python batch_clean_gpx.py --stats-only       # Solo mostrar estadísticas
    python batch_clean_gpx.py --file ruta.gpx    # Procesar un solo archivo

Requisitos:
    pip install gpxpy
"""

import argparse
import logging
import sys
from pathlib import Path
from typing import List, Tuple

import gpxpy
from gpxpy.gpx import GPX

from gps_cleaner import clean_gps_track, cleaning_stats, MAX_SPEED_KMH, MIN_DISTANCE_M, SMOOTH_WINDOW

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("batch-clean-gpx")

DEFAULT_DATA_DIR = Path(__file__).parent / "data"


def extract_points(gpx_file_path: Path) -> Tuple[List[Tuple[float, float, str]], dict]:
    """Extrae todos los puntos GPS de un archivo GPX."""
    with open(gpx_file_path, "r", encoding="utf-8") as f:
        gpx_content = f.read()
    gpx = gpxpy.parse(gpx_content)
    metadata = {
        "creator": getattr(gpx, "creator", "OptiBus GPS Cleaner"),
        "name": gpx.name or gpx_file_path.stem,
        "description": gpx.description or "",
        "track_names": [],
    }
    points: List[Tuple[float, float, str]] = []
    for track in gpx.tracks:
        track_name = track.name or "Unnamed"
        metadata["track_names"].append(track_name)
        for segment in track.segments:
            for point in segment.points:
                if point.time:
                    iso_time = point.time.strftime("%Y-%m-%dT%H:%M:%SZ")
                else:
                    iso_time = ""
                points.append((point.latitude, point.longitude, iso_time))
    return points, metadata


def _build_gpx_xml_manual(
    cleaned_points: List[Tuple[float, float, str]],
    metadata: dict,
) -> str:
    """Construye GPX XML manualmente (sin dependencia de lxml)."""
    from xml.dom.minidom import parseString
    from xml.etree.ElementTree import Element, SubElement, tostring

    gpx_el = Element(
        "gpx", {
            "version": "1.1",
            "creator": metadata.get("creator", "OptiBus GPS Cleaner (DevSecOps)"),
            "xmlns": "http://www.topografix.com/GPX/1/1",
            "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
            "xsi:schemaLocation": "http://www.topografix.com/GPX/1/1 "
            "http://www.topografix.com/GPX/1/1/gpx.xsd",
        },
    )
    meta_el = SubElement(gpx_el, "metadata")
    name_el = SubElement(meta_el, "name")
    name_el.text = metadata.get("name", "Ruta")
    if metadata.get("description"):
        desc_el = SubElement(meta_el, "desc")
        desc_el.text = metadata["description"]
    trk_el = SubElement(gpx_el, "trk")
    trk_name_el = SubElement(trk_el, "name")
    trk_name_el.text = metadata.get("name", "Ruta")
    trkseg_el = SubElement(trk_el, "trkseg")
    for lat, lon, iso_time in cleaned_points:
        trkpt_el = SubElement(trkseg_el, "trkpt", {"lat": str(lat), "lon": str(lon)})
        time_el = SubElement(trkpt_el, "time")
        time_el.text = iso_time.replace("Z", "")
    raw_xml = tostring(gpx_el, encoding="unicode")
    dom = parseString(raw_xml)
    return dom.toprettyxml(indent="  ")


def _build_gpx_xml_lxml(
    cleaned_points: List[Tuple[float, float, str]],
    metadata: dict,
    original_gpx: GPX,
) -> str:
    """Construye GPX XML usando lxml para preservar namespaces."""
    from lxml import etree
    nsmap = {None: "http://www.topografix.com/GPX/1/1", "xsi": "http://www.w3.org/2001/XMLSchema-instance"}
    gpx_el = etree.Element("gpx", nsmap=nsmap)
    gpx_el.set("version", "1.1")
    gpx_el.set("creator", "OptiBus GPS Cleaner (DevSecOps)")
    gpx_el.set("{http://www.w3.org/2001/XMLSchema-instance}schemaLocation",
               "http://www.topografix.com/GPX/1/1 http://www.topografix.com/GPX/1/1/gpx.xsd")
    meta_el = etree.SubElement(gpx_el, "metadata")
    name_el = etree.SubElement(meta_el, "name")
    name_el.text = metadata.get("name", "Ruta")
    if metadata.get("description"):
        desc_el = etree.SubElement(meta_el, "desc")
        desc_el.text = metadata["description"]
    trk_el = etree.SubElement(gpx_el, "trk")
    trk_name_el = etree.SubElement(trk_el, "name")
    trk_name_el.text = metadata.get("name", "Ruta")
    trkseg_el = etree.SubElement(trk_el, "trkseg")
    for lat, lon, iso_time in cleaned_points:
        trkpt_el = etree.SubElement(trkseg_el, "trkpt")
        trkpt_el.set("lat", str(lat))
        trkpt_el.set("lon", str(lon))
        time_el = etree.SubElement(trkpt_el, "time")
        time_el.text = iso_time.replace("Z", "")
    return etree.tostring(gpx_el, pretty_print=True, encoding="unicode", xml_declaration=True)


def build_clean_gpx(
    cleaned_points: List[Tuple[float, float, str]],
    metadata: dict,
    original_gpx: GPX,
) -> str:
    """Construye GPX XML a partir de puntos limpios y metadatos de GPX original."""
    try:
        from lxml import etree  # noqa: F401
        return _build_gpx_xml_lxml(cleaned_points, metadata, original_gpx)
    except ImportError:
        return _build_gpx_xml_manual(cleaned_points, metadata)


def build_clean_gpx_from_points(
    cleaned_points: List[Tuple[float, float, str]],
    name: str = "Ruta Limpiada",
    description: str = "",
    creator: str = "OptiBus GPS Cleaner (DevSecOps)",
) -> str:
    """
    Genera un archivo GPX XML a partir de puntos limpios sin necesitar el GPX original.
    Usado por ingest_gpx.py para limpieza in-place.

    Args:
        cleaned_points: Lista de (lat, lon, iso_time) ordenados y limpiados.
        name: Nombre de la ruta.
        description: Descripción opcional.
        creator: Atributo creator del GPX.

    Returns:
        String XML del GPX listo para escribir a disco.
    """
    metadata = {"name": name, "description": description, "creator": creator}
    return _build_gpx_xml_manual(cleaned_points, metadata)


# ── Batch processor (resto del código se mantiene igual) ──

def process_single_file(
    gpx_path: Path,
    max_speed_kmh: float = MAX_SPEED_KMH,
    min_distance_m: float = MIN_DISTANCE_M,
    smooth_window: int = SMOOTH_WINDOW,
    dry_run: bool = False,
) -> dict:
    logger.info(f"Procesando: {gpx_path.name}")
    try:
        raw_points, metadata = extract_points(gpx_path)
    except Exception as e:
        logger.error(f"Error parseando {gpx_path.name}: {e}")
        return {"error": str(e), "file": str(gpx_path)}
    raw_count = len(raw_points)
    logger.info(f"  Puntos crudos extraídos: {raw_count}")
    if raw_count < 3:
        logger.warning(f"  {gpx_path.name} tiene menos de 3 puntos. Saltando.")
        return {"file": str(gpx_path), "error": "Menos de 3 puntos", "puntos_crudos": raw_count}
    try:
        cleaned_points = clean_gps_track(raw_points, max_speed_kmh=max_speed_kmh,
                                         min_distance_m=min_distance_m, smooth_window=smooth_window)
    except Exception as e:
        logger.error(f"Error limpiando {gpx_path.name}: {e}", exc_info=True)
        return {"error": str(e), "file": str(gpx_path)}
    cleaned_count = len(cleaned_points)
    from gps_cleaner import parse_iso_time, haversine, speed_kmh_between, COORD_PRECISION
    parsed = []
    for lat, lon, ts in raw_points:
        uts = parse_iso_time(ts)
        if uts is not None:
            parsed.append((lat, lon, ts, uts))
    parsed.sort(key=lambda p: p[3])
    seen = set()
    dup_count = 0
    for lat, lon, ts, _ in parsed:
        key = (round(lat, COORD_PRECISION), round(lon, COORD_PRECISION))
        if key in seen:
            dup_count += 1
        else:
            seen.add(key)
    ghost_count = 0
    speed_count = 0
    static_count = 0
    if len(parsed) >= 2:
        deduped_list = []
        seen2 = set()
        for lat, lon, ts, uts in parsed:
            key = (round(lat, COORD_PRECISION), round(lon, COORD_PRECISION))
            if key not in seen2:
                seen2.add(key)
                deduped_list.append((lat, lon, ts, uts))
        for i in range(1, len(deduped_list)):
            spd = speed_kmh_between(deduped_list[i-1][0], deduped_list[i-1][1], deduped_list[i-1][3],
                                    deduped_list[i][0], deduped_list[i][1], deduped_list[i][3])
            if spd > max_speed_kmh:
                speed_count += 1
        last_p = deduped_list[0]
        for i in range(1, len(deduped_list)):
            curr = deduped_list[i]
            dist = haversine(last_p[0], last_p[1], curr[0], curr[1])
            dt = abs(curr[3] - last_p[3])
            if dist < min_distance_m and dt < 30.0:
                static_count += 1
            else:
                last_p = curr
        total_removed = raw_count - cleaned_count
        ghost_count = max(0, total_removed - dup_count - speed_count - static_count)
    stats = cleaning_stats(raw_count=raw_count, cleaned_count=cleaned_count,
                           duplicates=dup_count, ghosts=ghost_count,
                           speed_removed=speed_count, static_removed=static_count)
    stats["file"] = str(gpx_path.name)
    if not dry_run and cleaned_count >= 2:
        output_path = gpx_path.parent / f"{gpx_path.stem}_cleaned.gpx"
        try:
            with open(gpx_path, "r", encoding="utf-8") as f:
                original_gpx = gpxpy.parse(f.read())
            gpx_xml = build_clean_gpx(cleaned_points, metadata, original_gpx)
            with open(output_path, "w", encoding="utf-8") as f:
                f.write(gpx_xml)
            logger.info(f"  ✅ Guardado: {output_path.name} ({cleaned_count} puntos)")
            stats["output_file"] = str(output_path.name)
        except Exception as e:
            logger.error(f"  ❌ Error guardando {output_path.name}: {e}", exc_info=True)
            stats["error"] = str(e)
    return stats


def process_all_files(
    data_dir: Path, max_speed_kmh: float = MAX_SPEED_KMH,
    min_distance_m: float = MIN_DISTANCE_M, smooth_window: int = SMOOTH_WINDOW,
    dry_run: bool = False,
) -> List[dict]:
    gpx_files = sorted([f for f in data_dir.glob("*.gpx") if "_cleaned" not in f.stem])
    if not gpx_files:
        logger.warning(f"No se encontraron archivos .gpx en {data_dir}")
        return []
    logger.info(f"Encontrados {len(gpx_files)} archivo(s) .gpx para procesar")
    logger.info(f"Parámetros: vel máx={max_speed_kmh:.0f} km/h, "
                f"dist mín={min_distance_m:.1f}m, suavizado={smooth_window}")
    results = []
    for gpx_path in gpx_files:
        results.append(process_single_file(gpx_path, max_speed_kmh=max_speed_kmh,
                                           min_distance_m=min_distance_m,
                                           smooth_window=smooth_window, dry_run=dry_run))
    total_raw = sum(r.get("puntos_crudos", 0) for r in results)
    total_clean = sum(r.get("puntos_limpios", 0) for r in results)
    logger.info("=" * 50 + "\n📊 RESUMEN: %d archivos, %d → %d pts (%.1f%% eliminado)\n  Duplicados:%d Ghost:%d Velocidad:%d Estático:%d",
                len(results), total_raw, total_clean,
                round((total_raw - total_clean) / max(total_raw, 1) * 100, 1),
                sum(r.get("duplicados", 0) for r in results),
                sum(r.get("multipath_ghosts", 0) for r in results),
                sum(r.get("velocidad_excesiva", 0) for r in results),
                sum(r.get("ruido_estatico", 0) for r in results))
    return results


def main():
    parser = argparse.ArgumentParser(description="Batch GPX Cleaner - OptiBus DevSecOps")
    parser.add_argument("--dir", type=Path, default=DEFAULT_DATA_DIR, help="Directorio con GPX")
    parser.add_argument("--file", type=str, default=None, help="Procesar un solo archivo")
    parser.add_argument("--speed", type=float, default=MAX_SPEED_KMH, help="Velocidad máx km/h")
    parser.add_argument("--distance", type=float, default=MIN_DISTANCE_M, help="Distancia mín m")
    parser.add_argument("--smooth", type=int, default=SMOOTH_WINDOW, help="Ventana suavizado (impar)")
    parser.add_argument("--stats-only", action="store_true", help="Solo estadísticas")
    args = parser.parse_args()
    if args.smooth % 2 == 0:
        logger.error("Ventana de suavizado debe ser impar")
        sys.exit(1)
    data_dir = args.dir.resolve()
    if not data_dir.is_dir():
        logger.error(f"Directorio no existe: {data_dir}")
        sys.exit(1)
    logger.info("🚌 OptiBus Batch GPX Cleaner | Dir: %s | Vel máx: %.0f km/h | Dist mín: %.1f m | Suavizado: %d",
                data_dir, args.speed, args.distance, args.smooth)
    if args.file:
        gpx_path = data_dir / args.file
        if not gpx_path.exists():
            logger.error(f"Archivo no encontrado: {gpx_path}")
            sys.exit(1)
        result = process_single_file(gpx_path, max_speed_kmh=args.speed,
                                     min_distance_m=args.distance,
                                     smooth_window=args.smooth, dry_run=args.stats_only)
        if "error" not in result:
            print(f"\n📄 {result['file']}: {result['puntos_crudos']} → {result['puntos_limpios']} pts "
                  f"({result['porcentaje_eliminado']}% eliminado)")
    else:
        process_all_files(data_dir, max_speed_kmh=args.speed, min_distance_m=args.distance,
                          smooth_window=args.smooth, dry_run=args.stats_only)


if __name__ == "__main__":
    main()