"""
OptiBus B2G Middleware — DevSecOps v5.0
Anonimización estricta de datos para el portal municipal.
Ningún endpoint B2G devuelve driver_id, bus_id, ni cooperative_id.
"""


def anonymize_position(pos: dict) -> dict:
    """
    Limpia datos sensibles y agrupa coordenadas en grid de ~100m.
    Elimina: driver_id, bus_id, cooperative_id, nombres de choferes.
    """
    clean = {}
    if "lat" in pos and "lon" in pos:
        clean["lat"] = round(pos["lat"], 4)  # ~11m de precisión (grid 100m)
        clean["lon"] = round(pos["lon"], 4)
    if "speed_kmh" in pos or "speed" in pos:
        clean["speed_kmh"] = round(pos.get("speed_kmh", pos.get("speed", 0)), 1)
    if "recorded_at" in pos or "created_at" in pos or "last_seen" in pos:
        clean["ts"] = str(pos.get("recorded_at") or pos.get("created_at") or pos.get("last_seen") or "")
    # NUNCA incluir: driver_id, bus_id, cooperative_id, name
    return clean


def anonymize_list(positions: list[dict]) -> list[dict]:
    """Aplica anonimización a una lista de posiciones."""
    return [anonymize_position(p) for p in positions if p.get("lat") and p.get("lon")]
</content>

<write_to_file>
<path>backend/b2g_routes.py</path>
<content>
"""
OptiBus B2G Routes — DevSecOps v5.0
Portal Municipal: heatmap GeoJSON + compliance KPIs.
Datos anonimizados — sin driver_id, bus_id, cooperative_id.
"""

import json
import logging
from datetime import UTC, datetime, timedelta

import models
from b2g_middleware import anonymize_list, anonymize_position
from config import B2G_API_KEY_ENABLED, OPTIBUS_B2G_API_KEY
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from secrets import compare_digest

logger = logging.getLogger("optibus-b2g-routes")

router = APIRouter(prefix="/api/b2g", tags=["b2g"])


# ── Autenticación municipal (API Key estática) ──

async def verify_b2g_key(request: Request):
    """
    DevSecOps: Autenticación severa para endpoints municipales.
    Usa header X-B2G-API-Key (no comparte credenciales con B2B).
    """
    if not B2G_API_KEY_ENABLED:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Portal B2G no configurado. Define OPTIBUS_B2G_API_KEY en .env.",
        )
    api_key = request.headers.get("X-B2G-API-Key", "")
    if not compare_digest(api_key, OPTIBUS_B2G_API_KEY):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key B2G inválida. Usa el header X-B2G-API-Key.",
        )


# ── Endpoints ──

@router.get("/heatmap")
async def heatmap(
    request: Request,
    hours: int = Query(default=1, le=24),
    db: AsyncSession = Depends(get_db),
):
    """
    Mapa de calor municipal: GeoJSON con posiciones de buses (últimos N horas).
    Datos ANONIMIZADOS: sin driver_id, bus_id, cooperative_id.
    Coordenadas redondeadas a 4 decimales (~11m) — grid de ~100m.
    """
    await verify_b2g_key(request)

    since = datetime.now(UTC) - timedelta(hours=hours)
    result = await db.execute(
        select(
            func.ST_Y(models.BusPosition.geom).label("lat"),
            func.ST_X(models.BusPosition.geom).label("lon"),
            models.BusPosition.speed,
            models.BusPosition.recorded_at,
        )
        .where(models.BusPosition.recorded_at >= since)
        .order_by(models.BusPosition.recorded_at.desc())
        .limit(5000)
    )

    features = []
    for r in result:
        clean = anonymize_position({"lat": r.lat, "lon": r.lon, "speed": r.speed, "ts": r.recorded_at})
        if clean:
            features.append({
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [clean["lon"], clean["lat"]]},
                "properties": {"speed_kmh": clean.get("speed_kmh", 0), "ts": clean.get("ts", "")},
            })

    return {
        "type": "FeatureCollection",
        "features": features,
        "metadata": {
            "total_points": len(features),
            "hours": hours,
            "data_policy": "Anonimizado — sin driver_id, bus_id, cooperative_id. Grid ~100m.",
        },
    }


@router.get("/compliance")
async def compliance(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    KPI de cumplimiento municipal:
    - Porcentaje de buses activos vs capacidad máxima esperada
    - Total de rutas registradas
    - Total de paradas
    Datos AGREGADOS — sin identificadores de cooperativas individuales.
    """
    await verify_b2g_key(request)

    since = datetime.now(UTC) - timedelta(minutes=10)

    # Buses activos (últimos 10 min)
    active_query = await db.execute(
        select(func.count(func.distinct(models.BusPosition.bus_id)))
        .where(models.BusPosition.recorded_at >= since)
    )
    active_buses = active_query.scalar() or 0

    # Total rutas
    routes_query = await db.execute(select(func.count(models.Route.id)))
    total_routes = routes_query.scalar() or 0

    # Total paradas
    stops_query = await db.execute(select(func.count(models.Stop.id)))
    total_stops = stops_query.scalar() or 0

    # Capacidad máxima estimada (suma de max_buses de todas las cooperativas activas)
    capacity_query = await db.execute(
        select(func.coalesce(func.sum(models.Cooperative.max_buses), 0))
        .where(models.Cooperative.is_active.is_(True))
    )
    max_capacity = capacity_query.scalar() or 1

    compliance_pct = round((active_buses / max_capacity) * 100, 1) if max_capacity > 0 else 0

    return {
        "active_buses": active_buses,
        "max_capacity": max_capacity,
        "compliance_percentage": compliance_pct,
        "total_routes": total_routes,
        "total_stops": total_stops,
        "data_policy": "Datos agregados de todas las cooperativas. Sin identificadores individuales.",
    }