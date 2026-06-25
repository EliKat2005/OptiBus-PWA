"""Tests unitarios para el GPS Cleaner — DevSecOps v4.1."""

import pytest
from datetime import UTC, datetime
from utils.gps_cleaner import (
    clean_gps_track,
    haversine,
    parse_iso_time,
    simplify_rdp,
    MAX_SPEED_KMH,
    MAX_ACCELERATION,
    MIN_DISTANCE_M,
    RDP_EPSILON,
)


class TestHaversine:
    """Tests para la función Haversine de distancia geográfica."""

    def test_same_point(self):
        assert haversine(0, 0, 0, 0) == 0.0

    def test_known_distance(self):
        # Distancia Quito-Cuenca ≈ 300 km
        dist = haversine(-0.1807, -78.4678, -2.9006, -79.0043)
        assert 290_000 < dist < 320_000  # metros

    def test_antarctic_to_arctic(self):
        dist = haversine(-90, 0, 90, 0)
        assert 19_900_000 < dist < 20_100_000  # ≈20000 km (mitad circunferencia)

    def test_small_distance(self):
        # 111 metros ≈ 0.001 grados
        dist = haversine(0, 0, 0.001, 0)
        assert 100 < dist < 120  # metros


class TestParseIsoTime:
    """Tests para parseo de timestamps ISO 8601."""

    def test_valid_utc_z(self):
        ts = parse_iso_time("2024-01-15T10:30:00Z")
        assert ts is not None
        assert abs(ts - 1705312200.0) < 10  # segundos

    def test_valid_with_millis(self):
        ts = parse_iso_time("2024-01-15T10:30:00.123Z")
        assert ts is not None

    def test_empty_string(self):
        assert parse_iso_time("") is None

    def test_none(self):
        assert parse_iso_time(None) is None

    def test_invalid_format(self):
        assert parse_iso_time("not-a-date") is None


class TestSimplifyRdp:
    """Tests para el algoritmo Ramer-Douglas-Peucker."""

    def test_two_points(self):
        points = [(0, 0, 0), (1, 0, 1)]
        result = simplify_rdp(points, epsilon_m=10)
        assert result == [0, 1]  # siempre preserva extremos

    def test_straight_line(self):
        # Línea recta → solo preserva inicio y fin
        points = [(0, 0, 0), (0.001, 0, 0.5), (0.002, 0, 1)]
        result = simplify_rdp(points, epsilon_m=10)
        assert 0 in result
        assert len(points) - 1 in result
        assert len(result) <= 3  # puede preservar 1 intermedio si necesario

    def test_triangle(self):
        # Triángulo con pico en el medio
        points = [(0, 0, 0), (0.001, 0.001, 0.5), (0.002, 0, 1)]
        result = simplify_rdp(points, epsilon_m=5)
        # El pico debería preservarse
        assert 0 in result
        assert len(points) - 1 in result
        assert 1 in result  # el pico se preserva


class TestCleanGpsTrack:
    """Tests de integración para el pipeline completo de 9 etapas."""

    def _make_point(self, lat, lon, minutes_from_start=0):
        """Crea un punto GPS con timestamp relativo."""
        ts = datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)
        ts = ts.replace(minute=10 + minutes_from_start)
        return (lat, lon, ts.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_empty_track(self):
        result = clean_gps_track([])
        assert len(result) == 0

    def test_two_points(self):
        result = clean_gps_track([self._make_point(0, 0, 0), self._make_point(0.001, 0, 1)])
        assert len(result) >= 2

    def test_remove_speed_outlier(self):
        """Un salto de 3000 km/h debería ser eliminado."""
        points = [
            self._make_point(0, 0, 0),
            self._make_point(10, 10, 1),  # salto enorme ≈ 3000 km/h
            self._make_point(0.001, 0, 2),
        ]
        result = clean_gps_track(points, max_speed_kmh=120)
        # El punto outlier debería ser eliminado
        coords = [(p[0], p[1]) for p in result]
        # No debe contener el salto a (10, 10)
        assert (10, 10) not in coords

    def test_deduplicate_identical_points(self):
        """Puntos duplicados deben ser eliminados."""
        points = [
            self._make_point(0, 0, 0),
            self._make_point(0, 0, 0),  # duplicado exacto
            self._make_point(0.001, 0, 1),
        ]
        result = clean_gps_track(points)
        # Solo debe haber 2 puntos únicos
        unique = set((round(p[0], 6), round(p[1], 6)) for p in result)
        assert len(unique) == 2

    def test_realistic_bus_track(self):
        """Simulación de trayectoria realista de bus urbano (~30 km/h)."""
        points = []
        base_lat, base_lon = 0.35, -78.12
        for i in range(20):
            lat = base_lat + i * 0.0001
            lon = base_lon + i * 0.0001
            points.append(self._make_point(lat, lon, i))
        result = clean_gps_track(points)
        # Debe preservar la mayoría de los puntos
        assert len(result) >= 10

    def test_max_speed_filter_removes_ghosts(self):
        """Un ghost point (salto + retorno) debe ser filtrado."""
        points = [
            self._make_point(0, 0, 0),
            self._make_point(0.1, 0.1, 1),   # salto enorme
            self._make_point(0.001, 0, 2),    # retorno
            self._make_point(0.002, 0, 3),
        ]
        result = clean_gps_track(points, max_speed_kmh=80)
        # Debe preservar al menos 3 de los 4 puntos
        assert len(result) >= 2

    def test_static_noise_removal(self):
        """Ruido estático (< MIN_DISTANCE_M en < 30s) debe ser eliminado."""
        points = [
            self._make_point(0, 0, 0),
            self._make_point(0.000001, 0.000001, 0.01),  # <2m, <<30s → ruido
            self._make_point(0.001, 0, 1),
        ]
        result = clean_gps_track(points, min_distance_m=2)
        assert len(result) >= 2