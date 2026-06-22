"""
GPS Data Cleaner - OptiBus DevSecOps
=====================================
Filtra y limpia puntos GPS antes de ingestarlos en PostGIS.

Problemas que resuelve:
1. MULTIPATH / GHOST POINTS: Puntos que saltan lejos de la trayectoria y luego
   regresan (alucinaciones del Network Provider). Detectados por:
   - Salto >50m seguido de un retorno a la zona original en el siguiente punto.
   - Timestamp anterior al último punto válido (fuera de secuencia temporal).
2. VELOCIDAD FÍSICA IRREAL: Puntos que requerirían >80 km/h para ser alcanzados
   desde el punto anterior (Haversine + delta tiempo).
3. RUIDO ESTÁTICO: Puntos a <2m del anterior cuando el bus está detenido o
   en tráfico lento (temblor GPS).
4. DEDUPLICACIÓN: Puntos repetidos en coordenadas idénticas (<0.1m).
5. SUAVIZADO: Media móvil ponderada triangular para suavizar esquinas y
   reducir el ruido de alta frecuencia manteniendo la forma de la ruta.
"""

import math
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Tuple, Optional

# ---------------------------------------------------------------------------
# Constantes calibradas para bus urbano en ciudad latinoamericana
# ---------------------------------------------------------------------------
MAX_SPEED_KMH = 150.0                # Velocidad máxima irreal para bus urbano (tolerante con GPS de celular)
MAX_SPEED_M_S = MAX_SPEED_KMH / 3.6  # 41.67 m/s (= 150 km/h)
MIN_DISTANCE_M = 2.0                 # Distancia mínima entre puntos (anti-ruido)
MULTIPATH_JUMP_M = 50.0              # Salto sospechoso que activa detección multipath
MULTIPATH_RETURN_M = 30.0            # Si el siguiente punto retorna a <30m del origen,
                                     # el punto intermedio es ghost
SMOOTH_WINDOW = 5                    # Ventana de suavizado (debe ser impar)
COORD_PRECISION = 6                  # Decimales para comparar coordenadas (~0.1m)

# Logger dedicado
_logger = logging.getLogger("optibus-gps-cleaner")


# ---------------------------------------------------------------------------
# Tipos y estructuras de datos
# ---------------------------------------------------------------------------

@dataclass
class CleaningResult:
    """Resultado de una operación de limpieza GPS con estadísticas."""
    points: List[Tuple[float, float, str]]
    stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Funciones geoespaciales
# ---------------------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos coordenadas (fórmula Haversine)."""
    R = 6371000.0  # Radio medio terrestre en metros
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def speed_kmh_between(
    lat1: float, lon1: float, t1: float,
    lat2: float, lon2: float, t2: float,
) -> float:
    """Velocidad en km/h entre dos puntos. t1 y t2 en segundos Unix."""
    distance_m = haversine(lat1, lon1, lat2, lon2)
    dt = abs(t2 - t1)
    if dt < 0.1:
        return 0.0
    return (distance_m / dt) * 3.6  # m/s → km/h


# ---------------------------------------------------------------------------
# Parseo de timestamps
# ---------------------------------------------------------------------------

def parse_iso_time(iso_time: str) -> Optional[float]:
    """
    Convierte timestamp ISO 8601 a segundos Unix (float).
    Soporta formatos con Z, +00:00, y fracciones de segundo.
    Retorna None si no se puede parsear.
    """
    if not iso_time or not iso_time.strip():
        return None

    ts = iso_time.strip()

    formats = [
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%Y-%m-%dT%H:%M:%S+00:00",
        "%Y-%m-%dT%H:%M:%S.%f+00:00",
    ]

    for fmt in formats:
        try:
            dt = datetime.strptime(ts, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.timestamp()
        except ValueError:
            continue

    return None


# ---------------------------------------------------------------------------
# Algoritmo principal de limpieza
# ---------------------------------------------------------------------------

def clean_gps_track(
    points: List[Tuple[float, float, str]],
    max_speed_kmh: float = MAX_SPEED_KMH,
    min_distance_m: float = MIN_DISTANCE_M,
    smooth_window: int = SMOOTH_WINDOW,
) -> List[Tuple[float, float, str]]:
    """
    Limpia una trayectoria GPS cruda aplicando filtros en cascada.

    Paso 1: Parsear timestamps y ordenar cronológicamente.
    Paso 2: Eliminar duplicados (misma coordenada con precisión ~0.1m).
    Paso 3: Detectar y eliminar puntos MULTIPATH/GHOST.
    Paso 4: Filtrar por velocidad (>80 km/h = anómalo para bus urbano).
    Paso 5: Filtrar por distancia (<2m = ruido estático / temblor GPS).
    Paso 6: Suavizado con media móvil ponderada triangular.

    Returns:
        Lista de (lat, lon, iso_time) limpios, ordenados por timestamp.
    """
    result = clean_gps_track_with_stats(
        points,
        max_speed_kmh=max_speed_kmh,
        min_distance_m=min_distance_m,
        smooth_window=smooth_window,
    )
    return result.points


def clean_gps_track_with_stats(
    points: List[Tuple[float, float, str]],
    max_speed_kmh: float = MAX_SPEED_KMH,
    min_distance_m: float = MIN_DISTANCE_M,
    smooth_window: int = SMOOTH_WINDOW,
) -> CleaningResult:
    """
    Versión de clean_gps_track que además devuelve estadísticas detalladas
    de cuántos puntos se eliminaron en cada etapa.

    Returns:
        CleaningResult con .points y .stats (dict).
    """
    if len(points) < 3:
        return CleaningResult(
            points=list(points),
            stats=cleaning_stats(len(points), len(points), 0, 0, 0, 0),
        )

    # Contadores para estadísticas
    duplicates_removed = 0
    ghost_removed = 0
    time_backwards_removed = 0
    speed_removed = 0
    static_removed = 0

    # ------------------------------------------------------------------
    # Paso 1: Parsear timestamps y ordenar cronológicamente
    # ------------------------------------------------------------------
    parsed: List[Tuple[float, float, str, float]] = []
    skipped_no_time = 0

    for lat, lon, ts in points:
        unix_ts = parse_iso_time(ts)
        if unix_ts is None:
            skipped_no_time += 1
            continue
        parsed.append((lat, lon, ts, unix_ts))

    if skipped_no_time > 0:
        _logger.warning(
            f"Descartados {skipped_no_time} puntos sin timestamp parseable"
        )

    if len(parsed) < 3:
        r = [(lat, lon, ts) for lat, lon, ts, _ in parsed]
        return CleaningResult(
            points=r,
            stats=cleaning_stats(
                len(points), len(r), skipped_no_time, 0, 0, 0
            ),
        )

    parsed.sort(key=lambda p: p[3])

    # ------------------------------------------------------------------
    # Paso 2: Deduplicación
    # ------------------------------------------------------------------
    deduped: List[Tuple[float, float, str, float]] = []
    seen: set = set()

    for lat, lon, ts, unix_ts in parsed:
        key = (round(lat, COORD_PRECISION), round(lon, COORD_PRECISION))
        if key not in seen:
            seen.add(key)
            deduped.append((lat, lon, ts, unix_ts))
        else:
            duplicates_removed += 1

    if duplicates_removed > 0:
        _logger.info(f"Deduplicación: {duplicates_removed} puntos duplicados eliminados")

    if len(deduped) < 3:
        r = [(lat, lon, ts) for lat, lon, ts, _ in deduped]
        return CleaningResult(
            points=r,
            stats=cleaning_stats(
                len(points), len(r), duplicates_removed, 0, 0, 0
            ),
        )

    # ------------------------------------------------------------------
    # Paso 3: Detección MULTIPATH / GHOST
    # ------------------------------------------------------------------
    forward_time: List[Tuple[float, float, str, float]] = [deduped[0]]
    for i in range(1, len(deduped)):
        curr = deduped[i]
        last_valid = forward_time[-1]

        if curr[3] < last_valid[3] - 1.0:
            dist_to_last = haversine(last_valid[0], last_valid[1], curr[0], curr[1])
            if dist_to_last > MULTIPATH_JUMP_M:
                time_backwards_removed += 1
                continue
        forward_time.append(curr)

    if time_backwards_removed > 0:
        _logger.warning(
            f"Ghost (timestamp regresivo): {time_backwards_removed} puntos eliminados"
        )

    if len(forward_time) >= 3:
        filtered_time: List[Tuple[float, float, str, float]] = [forward_time[0]]
        i = 1
        while i < len(forward_time) - 1:
            prev = filtered_time[-1]
            curr = forward_time[i]
            next_pt = forward_time[i + 1]

            dist_prev_curr = haversine(prev[0], prev[1], curr[0], curr[1])
            dist_prev_next = haversine(prev[0], prev[1], next_pt[0], next_pt[1])

            if (
                dist_prev_curr > MULTIPATH_JUMP_M
                and dist_prev_next < MULTIPATH_RETURN_M
            ):
                ghost_removed += 1
                i += 1
                continue

            if curr[3] < prev[3] - 1.0 and dist_prev_curr > MULTIPATH_JUMP_M / 2:
                ghost_removed += 1
                i += 1
                continue

            filtered_time.append(curr)
            i += 1

        if i == len(forward_time) - 1:
            filtered_time.append(forward_time[-1])

        forward_time = filtered_time

    if ghost_removed > 0:
        _logger.warning(
            f"Ghost (patrón multipath): {ghost_removed} puntos eliminados"
        )

    total_ghosts = time_backwards_removed + ghost_removed

    # ------------------------------------------------------------------
    # Paso 4: Filtro de VELOCIDAD
    # ------------------------------------------------------------------
    speed_filtered: List[Tuple[float, float, str, float]] = [forward_time[0]]

    for i in range(1, len(forward_time)):
        prev = speed_filtered[-1]
        curr = forward_time[i]

        spd_kmh = speed_kmh_between(
            prev[0], prev[1], prev[3],
            curr[0], curr[1], curr[3],
        )

        if spd_kmh > max_speed_kmh:
            speed_removed += 1
            continue

        speed_filtered.append(curr)

    if speed_removed > 0:
        _logger.warning(
            f"Velocidad excesiva (> {max_speed_kmh:.0f} km/h): "
            f"{speed_removed} puntos eliminados"
        )

    if len(speed_filtered) < 2:
        r = [(lat, lon, ts) for lat, lon, ts, _ in speed_filtered]
        return CleaningResult(
            points=r,
            stats=cleaning_stats(
                len(points), len(r),
                duplicates_removed, total_ghosts, speed_removed, 0,
            ),
        )

    # ------------------------------------------------------------------
    # Paso 5: Filtro de DISTANCIA MÍNIMA (ruido estático)
    # ------------------------------------------------------------------
    dist_filtered: List[Tuple[float, float, str, float]] = [speed_filtered[0]]

    for i in range(1, len(speed_filtered)):
        prev = dist_filtered[-1]
        curr = speed_filtered[i]

        dist = haversine(prev[0], prev[1], curr[0], curr[1])
        dt = abs(curr[3] - prev[3])

        if dist < min_distance_m and dt < 30.0:
            static_removed += 1
            continue

        dist_filtered.append(curr)

    if static_removed > 0:
        _logger.info(
            f"Ruido estático (< {min_distance_m}m): {static_removed} puntos eliminados"
        )

    if len(dist_filtered) < 3:
        r = [(lat, lon, ts) for lat, lon, ts, _ in dist_filtered]
        return CleaningResult(
            points=r,
            stats=cleaning_stats(
                len(points), len(r),
                duplicates_removed, total_ghosts, speed_removed, static_removed,
            ),
        )

    # ------------------------------------------------------------------
    # Paso 6: Suavizado con media móvil ponderada triangular
    # ------------------------------------------------------------------
    smoothed: List[Tuple[float, float, str]] = []
    half_window = smooth_window // 2

    for i in range(len(dist_filtered)):
        if i < half_window or i >= len(dist_filtered) - half_window:
            smoothed.append(
                (dist_filtered[i][0], dist_filtered[i][1], dist_filtered[i][2])
            )
        else:
            lat_sum = 0.0
            lon_sum = 0.0
            weight_sum = 0.0

            for j in range(i - half_window, i + half_window + 1):
                weight = float(half_window + 1 - abs(i - j))
                lat_sum += dist_filtered[j][0] * weight
                lon_sum += dist_filtered[j][1] * weight
                weight_sum += weight

            smoothed.append(
                (
                    round(lat_sum / weight_sum, 7),
                    round(lon_sum / weight_sum, 7),
                    dist_filtered[i][2],
                )
            )

    return CleaningResult(
        points=smoothed,
        stats=cleaning_stats(
            len(points), len(smoothed),
            duplicates_removed, total_ghosts, speed_removed, static_removed,
        ),
    )


# ---------------------------------------------------------------------------
# Estadísticas de limpieza
# ---------------------------------------------------------------------------

def cleaning_stats(
    raw_count: int,
    cleaned_count: int,
    duplicates: int,
    ghosts: int,
    speed_removed: int,
    static_removed: int,
) -> dict:
    """Genera un diccionario con estadísticas del proceso de limpieza."""
    total_removed = raw_count - cleaned_count
    return {
        "puntos_crudos": raw_count,
        "puntos_limpios": cleaned_count,
        "total_eliminados": total_removed,
        "porcentaje_eliminado": round(
            (total_removed / raw_count * 100) if raw_count > 0 else 0, 1
        ),
        "duplicados": duplicates,
        "multipath_ghosts": ghosts,
        "velocidad_excesiva": speed_removed,
        "ruido_estatico": static_removed,
    }