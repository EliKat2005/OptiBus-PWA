"""
GPS Data Cleaner - OptiBus DevSecOps v2.0
==========================================
Filtra, limpia y suaviza trayectorias GPS con algoritmos de nivel profesional.

Pipeline de 8 etapas:
1. Parseo de timestamps y orden cronológico
2. Deduplicación de puntos idénticos (<0.1m)
3. Detección MULTIPATH/GHOST (salto súbito + retorno)
4. Filtro de VELOCIDAD FÍSICA (>150 km/h irreal para bus urbano)
5. Filtro de ACELERACIÓN (>4 m/s² irreal para bus)
6. Filtro de CAMBIO DE DIRECCIÓN (heading >90° en <3s)
7. Detección de ESTACIONAMIENTO (preservar puntos en semáforos/paradas)
8. Suavizado Kalman-like (media móvil exponencial ponderada)
9. Ramer-Douglas-Peucker (simplificación preservando geometría)
"""

import logging
import math
from dataclasses import dataclass, field
from datetime import UTC, datetime

# ---------------------------------------------------------------------------
# Constantes calibradas para bus urbano en ciudad latinoamericana
# ---------------------------------------------------------------------------
MAX_SPEED_KMH = 150.0                # Velocidad máxima irreal (tolerante con GPS celular)
MAX_SPEED_M_S = MAX_SPEED_KMH / 3.6  # 41.67 m/s
MAX_ACCELERATION = 4.0               # m/s² — un bus urbano no acelera más de esto
MIN_DISTANCE_M = 2.0                 # Distancia mínima entre puntos (anti-ruido)
MULTIPATH_JUMP_M = 50.0              # Salto sospechoso que activa detección multipath
MULTIPATH_RETURN_M = 30.0            # Retorno al origen = ghost
HEADING_MAX_CHANGE_DEG = 90.0        # Cambio de dirección máximo en ventana corta
HEADING_WINDOW_S = 3.0               # Ventana para detectar zigzag de heading
SMOOTH_WINDOW = 5                    # Ventana de suavizado (impar)
COORD_PRECISION = 6                  # Decimales para comparar (~0.1m)
PARKING_SPEED_THRESHOLD = 2.0        # km/h — debajo de esto se considera detenido
PARKING_MIN_DURATION_S = 30.0        # segundos — preservar puntos si está detenido >30s
RDP_EPSILON = 5.0                    # metros — tolerancia para simplificación RDP

# Logger dedicado
_logger = logging.getLogger("optibus-gps-cleaner")


# ---------------------------------------------------------------------------
# Tipos
# ---------------------------------------------------------------------------

@dataclass
class CleaningResult:
    """Resultado de operación de limpieza GPS con estadísticas."""
    points: list[tuple[float, float, str]]
    stats: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Geoespacial
# ---------------------------------------------------------------------------

def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos coordenadas (Haversine)."""
    earth_radius = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return earth_radius * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Ángulo de heading entre dos puntos (0-360°, 0=Norte, 90=Este)."""
    dlon = math.radians(lon2 - lon1)
    lat1r = math.radians(lat1)
    lat2r = math.radians(lat2)
    y = math.sin(dlon) * math.cos(lat2r)
    x = math.cos(lat1r) * math.sin(lat2r) - math.sin(lat1r) * math.cos(lat2r) * math.cos(dlon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def heading_change(h1: float, h2: float) -> float:
    """Diferencia angular mínima entre dos headings (0-180°)."""
    diff = abs(h2 - h1)
    return min(diff, 360 - diff)


def speed_kmh_between(
    lat1: float, lon1: float, t1: float,
    lat2: float, lon2: float, t2: float,
) -> float:
    """Velocidad en km/h entre dos puntos (timestamps en segundos Unix)."""
    distance_m = haversine(lat1, lon1, lat2, lon2)
    dt = abs(t2 - t1)
    if dt < 0.1:
        return 0.0
    return (distance_m / dt) * 3.6


# ---------------------------------------------------------------------------
# Parseo de timestamps
# ---------------------------------------------------------------------------

def parse_iso_time(iso_time: str) -> float | None:
    """Convierte ISO 8601 a segundos Unix. Retorna None si no parseable."""
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
                dt = dt.replace(tzinfo=UTC)
            return dt.timestamp()
        except ValueError:
            continue
    return None


# ---------------------------------------------------------------------------
# Ramer-Douglas-Peucker (simplificación de trayectoria)
# ---------------------------------------------------------------------------

def _rdp_reduce(points: list[tuple[float, float, float]], epsilon: float, start: int, end: int, keep: list[int]) -> None:
    """Algoritmo RDP recursivo: marca índices a preservar."""
    if end - start <= 1:
        return

    x1, y1 = points[start][1], points[start][0]  # lon, lat
    x2, y2 = points[end][1], points[end][0]

    max_dist = 0.0
    max_idx = start + 1

    for i in range(start + 1, end):
        x0, y0 = points[i][1], points[i][0]
        # Distancia perpendicular del punto a la línea start-end
        numerator = abs((x2 - x1) * (y1 - y0) - (x1 - x0) * (y2 - y1))
        denominator = math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2)
        if denominator < 0.0001:
            dist = haversine(points[i][0], points[i][1], points[start][0], points[start][1])
        else:
            # Convertir distancia en grados a metros (~111 km por grado)
            dist = (numerator / denominator) * 111000.0
        if dist > max_dist:
            max_dist = dist
            max_idx = i

    if max_dist > epsilon:
        keep.append(max_idx)
        _rdp_reduce(points, epsilon, start, max_idx, keep)
        _rdp_reduce(points, epsilon, max_idx, end, keep)


def simplify_rdp(points: list[tuple[float, float, float]], epsilon_m: float = RDP_EPSILON) -> list[int]:
    """Simplifica una trayectoria con RDP. Retorna índices a preservar."""
    if len(points) <= 2:
        return list(range(len(points)))
    keep = [0, len(points) - 1]
    _rdp_reduce(points, epsilon_m, 0, len(points) - 1, keep)
    return sorted(set(keep))


# ---------------------------------------------------------------------------
# Algoritmo principal (8 etapas)
# ---------------------------------------------------------------------------

def clean_gps_track(
    points: list[tuple[float, float, str]],
    max_speed_kmh: float = MAX_SPEED_KMH,
    min_distance_m: float = MIN_DISTANCE_M,
    smooth_window: int = SMOOTH_WINDOW,
) -> list[tuple[float, float, str]]:
    result = clean_gps_track_with_stats(points, max_speed_kmh, min_distance_m, smooth_window)
    return result.points


def clean_gps_track_with_stats(
    points: list[tuple[float, float, str]],
    max_speed_kmh: float = MAX_SPEED_KMH,
    min_distance_m: float = MIN_DISTANCE_M,
    smooth_window: int = SMOOTH_WINDOW,
) -> CleaningResult:
    """Pipeline completo de limpieza GPS profesional en 8 etapas."""
    if len(points) < 3:
        return CleaningResult(points=list(points), stats=cleaning_stats(len(points), len(points), 0, 0, 0, 0, 0))

    duplicates = 0
    ghosts = 0
    speed_removed = 0
    accel_removed = 0
    heading_removed = 0
    static_removed = 0
    rdp_before = 0
    rdp_after = 0

    # ── ETAPA 1: Parsear y ordenar ──
    parsed: list[tuple[float, float, str, float]] = []
    skipped_no_time = 0
    for lat, lon, ts in points:
        ut = parse_iso_time(ts)
        if ut is not None:
            parsed.append((lat, lon, ts, ut))
        else:
            skipped_no_time += 1
    if skipped_no_time:
        _logger.warning(f"Descartados {skipped_no_time} puntos sin timestamp")
    if len(parsed) < 3:
        r = [(lat, lon, ts) for lat, lon, ts, _ in parsed]
        return CleaningResult(points=r, stats=cleaning_stats(len(points), len(r), skipped_no_time, 0, 0, 0, 0))
    parsed.sort(key=lambda p: p[3])

    # ── ETAPA 2: Deduplicación ──
    deduped: list[tuple[float, float, str, float]] = []
    seen: set = set()
    for lat, lon, ts, ut in parsed:
        key = (round(lat, COORD_PRECISION), round(lon, COORD_PRECISION))
        if key not in seen:
            seen.add(key)
            deduped.append((lat, lon, ts, ut))
        else:
            duplicates += 1
    if duplicates:
        _logger.info(f"Deduplicación: {duplicates} puntos eliminados")
    if len(deduped) < 3:
        r = [(lat, lon, ts) for lat, lon, ts, _ in deduped]
        return CleaningResult(points=r, stats=cleaning_stats(len(points), len(r), duplicates, 0, 0, 0, 0))

    # ── ETAPA 3: Multipath / Ghost ──
    time_forward: list[tuple[float, float, str, float]] = [deduped[0]]
    for i in range(1, len(deduped)):
        curr = deduped[i]
        last_valid = time_forward[-1]
        if curr[3] < last_valid[3] - 1.0:
            dist_to_last = haversine(last_valid[0], last_valid[1], curr[0], curr[1])
            if dist_to_last > MULTIPATH_JUMP_M:
                ghosts += 1
                continue
        time_forward.append(curr)
    if ghosts:
        _logger.warning(f"Ghost (timestamp regresivo): {ghosts} puntos eliminados")

    # Ghost pattern: salto >50m + retorno <30m
    if len(time_forward) >= 3:
        filtered: list[tuple[float, float, str, float]] = [time_forward[0]]
        pattern_ghosts = 0
        for i in range(1, len(time_forward) - 1):
            prev = filtered[-1]
            curr = time_forward[i]
            nxt = time_forward[i + 1]
            dist_pc = haversine(prev[0], prev[1], curr[0], curr[1])
            dist_pn = haversine(prev[0], prev[1], nxt[0], nxt[1])
            if dist_pc > MULTIPATH_JUMP_M and dist_pn < MULTIPATH_RETURN_M:
                pattern_ghosts += 1
                continue
            if curr[3] < prev[3] - 1.0 and dist_pc > MULTIPATH_JUMP_M / 2:
                pattern_ghosts += 1
                continue
            filtered.append(curr)
        if i == len(time_forward) - 2:
            filtered.append(time_forward[-1])
        time_forward = filtered
        ghosts += pattern_ghosts
        if pattern_ghosts:
            _logger.warning(f"Ghost (patrón multipath): {pattern_ghosts} puntos")

    # ── ETAPA 4: Velocidad ──
    speed_filtered: list[tuple[float, float, str, float]] = [time_forward[0]]
    for i in range(1, len(time_forward)):
        prev = speed_filtered[-1]
        curr = time_forward[i]
        spd = speed_kmh_between(prev[0], prev[1], prev[3], curr[0], curr[1], curr[3])
        if spd > max_speed_kmh:
            speed_removed += 1
            continue
        speed_filtered.append(curr)
    if speed_removed:
        _logger.warning(f"Velocidad >{max_speed_kmh:.0f} km/h: {speed_removed} puntos")

    # ── ETAPA 5: Aceleración ──
    accel_filtered: list[tuple[float, float, str, float]] = [speed_filtered[0]]
    for i in range(1, len(speed_filtered)):
        prev = accel_filtered[-1]
        curr = speed_filtered[i]
        dt = abs(curr[3] - prev[3])
        if dt > 0:
            v1 = haversine(prev[0], prev[1], curr[0], curr[1]) / dt  # m/s
            if i > 1:
                v0 = haversine(accel_filtered[-2][0], accel_filtered[-2][1], prev[0], prev[1]) / max(abs(prev[3] - accel_filtered[-2][3]), 0.1)
                accel = abs(v1 - v0) / dt
                if accel > MAX_ACCELERATION:
                    accel_removed += 1
                    continue
        accel_filtered.append(curr)
    if accel_removed:
        _logger.info(f"Aceleración >{MAX_ACCELERATION} m/s²: {accel_removed} puntos")

    # ── ETAPA 6: Heading (cambio brusco de dirección) ──
    heading_filtered: list[tuple[float, float, str, float]] = [accel_filtered[0]]
    for i in range(2, len(accel_filtered)):
        p0 = heading_filtered[-1]
        p1 = accel_filtered[i - 1]
        p2 = accel_filtered[i]
        h1 = bearing_deg(p0[0], p0[1], p1[0], p1[1])
        h2 = bearing_deg(p1[0], p1[1], p2[0], p2[1])
        change = heading_change(h1, h2)
        dt = p2[3] - p1[3]
        if dt < HEADING_WINDOW_S and change > HEADING_MAX_CHANGE_DEG:
            heading_removed += 1
            continue
        heading_filtered.append(p2)
    if heading_removed:
        _logger.info(f"Heading >{HEADING_MAX_CHANGE_DEG}°: {heading_removed} puntos")
    if len(heading_filtered) < 2:
        heading_filtered = accel_filtered

    # ── ETAPA 7: Preservar estacionamiento (no eliminar puntos en semáforos) ──
    dist_filtered: list[tuple[float, float, str, float]] = [heading_filtered[0]]
    for i in range(1, len(heading_filtered)):
        prev = dist_filtered[-1]
        curr = heading_filtered[i]
        dist = haversine(prev[0], prev[1], curr[0], curr[1])
        dt = abs(curr[3] - prev[3])
        # Si el bus está detenido (>30s), preservar el punto (es una parada real)
        if dist < min_distance_m and dt < PARKING_MIN_DURATION_S:
            # No eliminar — preservar como punto de estacionamiento
            dist_filtered.append(curr)
        elif dist < min_distance_m and dt < 30.0:
            static_removed += 1
            continue
        else:
            dist_filtered.append(curr)
    if static_removed:
        _logger.info(f"Ruido estático (<{min_distance_m}m): {static_removed} puntos")
    if len(dist_filtered) < 3:
        r = [(lat, lon, ts) for lat, lon, ts, _ in dist_filtered]
        return CleaningResult(points=r, stats=cleaning_stats(len(points), len(r), duplicates, ghosts, speed_removed, accel_removed + heading_removed, static_removed))

    # ── ETAPA 8: Suavizado Kalman-like (media móvil exponencial ponderada) ──
    smoothed: list[tuple[float, float, str]] = []
    half = smooth_window // 2
    for i in range(len(dist_filtered)):
        if i < half or i >= len(dist_filtered) - half:
            smoothed.append((dist_filtered[i][0], dist_filtered[i][1], dist_filtered[i][2]))
        else:
            lat_sum = 0.0
            lon_sum = 0.0
            weight_sum = 0.0
            for j in range(i - half, i + half + 1):
                weight = float(half + 1 - abs(i - j))
                lat_sum += dist_filtered[j][0] * weight
                lon_sum += dist_filtered[j][1] * weight
                weight_sum += weight
            smoothed.append((round(lat_sum / weight_sum, 7), round(lon_sum / weight_sum, 7), dist_filtered[i][2]))

    # ── ETAPA 9: Simplificación RDP ──
    rdp_before = len(smoothed)
    rdp_input = [(lat, lon, parse_iso_time(ts) or 0.0) for lat, lon, ts in smoothed]
    keep_indices = simplify_rdp(rdp_input, epsilon_m=RDP_EPSILON)
    simplified = [smoothed[i] for i in keep_indices if i < len(smoothed)]
    rdp_after = len(simplified)
    if rdp_before != rdp_after:
        _logger.info(f"RDP simplification: {rdp_before} → {rdp_after} puntos")

    return CleaningResult(
        points=simplified,
        stats=cleaning_stats(len(points), len(simplified), duplicates, ghosts, speed_removed, accel_removed + heading_removed, static_removed),
    )


# ---------------------------------------------------------------------------
# Estadísticas
# ---------------------------------------------------------------------------

def cleaning_stats(
    raw_count: int, cleaned_count: int,
    duplicates: int, ghosts: int,
    speed_removed: int, accel_heading_removed: int,
    static_removed: int,
) -> dict:
    total_removed = raw_count - cleaned_count
    return {
        "puntos_crudos": raw_count,
        "puntos_limpios": cleaned_count,
        "total_eliminados": total_removed,
        "porcentaje_eliminado": round((total_removed / raw_count * 100) if raw_count > 0 else 0, 1),
        "duplicados": duplicates,
        "multipath_ghosts": ghosts,
        "velocidad_excesiva": speed_removed,
        "aceleracion_heading": accel_heading_removed,
        "ruido_estatico": static_removed,
    }
