"""
OptiBus B2G Routes — DevSecOps v5.0
Portal Municipal: heatmap GeoJSON + compliance KPIs.
Datos anonimizados — sin driver_id, bus_id, cooperative_id.
"""

import logging
from datetime import UTC, datetime, timedelta
from secrets import compare_digest

import models
from b2g_middleware import anonymize_position
from config import B2G_API_KEY_ENABLED, OPTIBUS_B2G_API_KEY
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("optibus-b2g-routes")

router = APIRouter(prefix="/api/b2g", tags=["b2g"])


async def verify_b2g_key(request: Request):
    """
    DevSecOps: Autenticacion severa para endpoints municipales.
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
            detail="API Key B2G invalida. Usa el header X-B2G-API-Key.",
        )


@router.get("/heatmap")
async def heatmap(
    request: Request,
    hours: int = Query(default=1, le=24),
    db: AsyncSession = Depends(get_db),
):
    """
    Mapa de calor municipal: GeoJSON con posiciones de buses (ultimas N horas).
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
        clean = anonymize_position({
            "lat": r.lat,
            "lon": r.lon,
            "speed": r.speed,
            "ts": r.recorded_at,
        })
        if clean:
            features.append({
                "type": "Feature",
                "geometry": {
                    "type": "Point",
                    "coordinates": [clean["lon"], clean["lat"]],
                },
                "properties": {
                    "speed_kmh": clean.get("speed_kmh", 0),
                    "ts": clean.get("ts", ""),
                },
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
    - Porcentaje de buses activos vs capacidad maxima esperada
    - Total de rutas registradas
    - Total de paradas
    Datos AGREGADOS — sin identificadores de cooperativas individuales.
    """
    await verify_b2g_key(request)

    since = datetime.now(UTC) - timedelta(minutes=10)

    active_query = await db.execute(
        select(func.count(func.distinct(models.BusPosition.bus_id)))
        .where(models.BusPosition.recorded_at >= since)
    )
    active_buses = active_query.scalar() or 0

    routes_query = await db.execute(select(func.count(models.Route.id)))
    total_routes = routes_query.scalar() or 0

    stops_query = await db.execute(select(func.count(models.Stop.id)))
    total_stops = stops_query.scalar() or 0

    capacity_query = await db.execute(
        select(func.coalesce(func.sum(models.Cooperative.max_buses), 0))
        .where(models.Cooperative.is_active.is_(True))
    )
    max_capacity = capacity_query.scalar() or 1

    compliance_pct = (
        round((active_buses / max_capacity) * 100, 1)
        if max_capacity > 0 else 0
    )

    return {
        "active_buses": active_buses,
        "max_capacity": max_capacity,
        "compliance_percentage": compliance_pct,
        "total_routes": total_routes,
        "total_stops": total_stops,
        "data_policy": "Datos agregados de todas las cooperativas. Sin identificadores individuales.",
    }