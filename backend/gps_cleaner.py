"""
GPS Data Cleaner - OptiBus DevSecOps
Filtra y limpia puntos GPS antes de ingestarlos en PostGIS.

Problemas que resuelve:
1. Outliers: puntos que se desvían >50m de la trayectoria real (alucinaciones del GPS/Network)
2. Deduplicación: puntos repetidos en exactamente las mismas coordenadas
3. Ordenamiento: timestamps fuera de secuencia (Network Provider vs GPS)
4. Suavizado: reduce ruido manteniendo la forma de la ruta (media móvil ponderada)
"""

import math
from typing import List, Tuple


def haversine(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distancia en metros entre dos coordenadas (fórmula Haversine)."""
    R = 6371000.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def speed_between(
    lat1: float, lon1: float, t1: float,
    lat2: float, lon2: float, t2: float
) -> float:
    """Velocidad en m/s entre dos puntos. t1 y t2 en segundos Unix."""
    distance = haversine(lat1, lon1, lat2, lon2)
    dt = abs(t2 - t1)
    if dt < 0.5:
        return 0.0
    return distance / dt


def to_unix(iso_time: str) -> float:
    """Convierte timestamp ISO 8601 a segundos Unix."""
    from datetime import datetime, timezone

    # Formato: 2026-05-30T15:22:11Z
    try:
        dt = datetime.strptime(iso_time, "%Y-%m-%dT%H:%M:%SZ").replace(
            tzinfo=timezone.utc
        )
        return dt.timestamp()
    except ValueError:
        return 0.0


def clean_gps_track(
    points: List[Tuple[float, float, str]],
    max_speed_m_s: float = 30.0,
    min_distance_m: float = 0.5,
    outlier_distance_m: float = 50.0,
    smooth_window: int = 3,
) -> List[Tuple[float, float, str]]:
    """
    Limpia una trayectoria GPS cruda.

    Args:
        points: Lista de (lat, lon, iso_time) crudos del GPX.
        max_speed_m_s: Velocidad máxima permitida (m/s). Default 30 m/s = 108 km/h.
        min_distance_m: Distancia mínima entre puntos consecutivos. Puntos más
                        cercanos se consideran duplicados y se eliminan.
        outlier_distance_m: Distancia máxima desde el punto anterior para
                            considerar un punto como outlier. Puntos que saltan
                            más de esta distancia en 1 segundo se descartan.
        smooth_window: Tamaño de ventana para el suavizado (media móvil).
                       Debe ser impar. Default 3.

    Returns:
        Lista de (lat, lon, iso_time) limpios, ordenados por timestamp.
    """
    if len(points) < 3:
        return points

    # Paso 1: Ordenar por timestamp
    sorted_points = sorted(points, key=lambda p: to_unix(p[2]))

    # Paso 2: Eliminar duplicados exactos
    deduped: List[Tuple[float, float, str, float]] = []
    seen: set = set()
    for lat, lon, ts in sorted_points:
        key = (round(lat, 7), round(lon, 7))
        if key not in seen:
            seen.add(key)
            deduped.append((lat, lon, ts, to_unix(ts)))

    if len(deduped) < 3:
        return [(lat, lon, ts) for lat, lon, ts, _ in deduped]

    # Paso 3: Filtrar outliers por velocidad y distancia
    filtered: List[Tuple[float, float, str, float]] = [deduped[0]]

    for i in range(1, len(deduped)):
        prev = filtered[-1]
        curr = deduped[i]

        dist = haversine(prev[0], prev[1], curr[0], curr[1])
        dt = abs(curr[3] - prev[3])

        if dt < 0.5:
            # Timestamps demasiado cercanos: tomar el de mejor precisión
            # (el GPS provider suele tener timestamps más consistentes)
            # Si el punto anterior es muy cercano en el tiempo, omitir este
            if dist < outlier_distance_m:
                continue  # Es ruido
            # Si hay salto grande en poco tiempo, es outlier
            if dist > outlier_distance_m and dt < 2.0:
                continue  # Alucinación GPS: más de 50m en <2 segundos

        speed = dist / max(dt, 0.5)
        if speed > max_speed_m_s and dt < 5.0:
            # Más rápido que 108 km/h en < 5 segundos = outlier
            continue

        if dist < min_distance_m and dt < 5.0:
            # Punto demasiado cercano al anterior en poco tiempo
            continue

        filtered.append(curr)

    if len(filtered) < 2:
        return [(lat, lon, ts) for lat, lon, ts, _ in filtered]

    # Paso 4: Suavizado con media móvil ponderada
    smoothed: List[Tuple[float, float, str]] = []
    half_window = smooth_window // 2

    for i in range(len(filtered)):
        if i < half_window or i >= len(filtered) - half_window:
            # Bordes: sin suavizar
            smoothed.append(
                (filtered[i][0], filtered[i][1], filtered[i][2])
            )
        else:
            # Media móvil ponderada (el punto central pesa más)
            lat_sum = 0.0
            lon_sum = 0.0
            weight_sum = 0.0
            for j in range(i - half_window, i + half_window + 1):
                weight = 1.0 + half_window - abs(i - j)  # Peso triangular
                lat_sum += filtered[j][0] * weight
                lon_sum += filtered[j][1] * weight
                weight_sum += weight
            smoothed.append(
                (
                    round(lat_sum / weight_sum, 7),
                    round(lon_sum / weight_sum, 7),
                    filtered[i][2],
                )
            )

    return smoothed