"""
OptiBus GPS Routes — DevSecOps v4.0
Endpoints de GPS: update, owntracks, history, active buses, geofence, ETA.
Separado de main.py para mantener modularidad.
"""

import json
import logging
import math
import os
from datetime import UTC, datetime, timedelta

import models
from auth_utils import verify_api_key, verify_optional_auth
from config import APP_VERSION, BUS_ID_PATTERN
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, field_validator
from sqlalchemy import and_, desc, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from ws_manager import ConnectionManager

logger = logging.getLogger("optibus-gps-routes")

router = APIRouter(prefix="/api", tags=["gps"])

# WebSocket manager (inyectado desde main.py)
_ws_manager: ConnectionManager | None = None


def init_gps_routes(ws_manager: ConnectionManager):
    """Inicializa el módulo con el ConnectionManager."""
    global _ws_manager
    _ws_manager = ws_manager


# ── Pydantic Models ──


class GPSPayload(BaseModel):
    bus_id: str
    lat: float
    lon: float
    speed: float = 0.0
    route_id: int | None = None

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v):
        if not -90 <= v <= 90:
            raise ValueError("Latitud inválida")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v):
        if not -180 <= v <= 180:
            raise ValueError("Longitud inválida")
        return v

    @field_validator("bus_id")
    @classmethod
    def validate_bus_id(cls, v):
        if not BUS_ID_PATTERN.match(v):
            raise ValueError(
                "bus_id inválido: solo letras, números, _ - . (máx 100 caracteres)"
            )
        return v


# ── Endpoints ──


@router.post("/gps/update")
async def receive_gps(
    payload: GPSPayload,
    request: Request,
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Recibe posición GPS y la guarda en historial + broadcast WebSocket."""

    # Guardar en historial
    point = f"SRID=4326;POINT({payload.lon} {payload.lat})"
    try:
        db.add(
            models.BusPosition(
                bus_id=payload.bus_id,
                geom=func.ST_GeomFromText(point, 4326),
                speed=payload.speed,
                route_id=payload.route_id,
                recorded_at=datetime.now(UTC),
            )
        )
        await db.commit()
    except Exception as e:
        logger.error(f"Error guardando posición: {e}")
        await db.rollback()

    # Broadcast WebSocket
    if _ws_manager:
        await _ws_manager.broadcast(
            json.dumps(
                {
                    "type": "bus_positions",
                    "buses": [
                        {
                            "id": payload.bus_id,
                            "lat": payload.lat,
                            "lon": payload.lon,
                            "source": "real",
                            "route_id": payload.route_id,
                        }
                    ],
                }
            )
        )
    return {"status": "success"}


@router.post("/gps/owntracks")
async def receive_owntracks(
    payload: dict,
    request: Request,
    _auth: dict = Depends(verify_api_key),
):
    """Compatibilidad con Owntracks."""
    if payload.get("_type") == "location":
        lat, lon = payload.get("lat"), payload.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return {"status": "error"}
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return {"status": "error"}
        tracker_id = payload.get("tid", "BUS")
        if _ws_manager:
            await _ws_manager.broadcast(
                json.dumps(
                    {
                        "type": "bus_positions",
                        "buses": [
                            {
                                "id": f"BUS-{tracker_id.upper()}",
                                "lat": lat,
                                "lon": lon,
                                "source": "owntracks_native",
                            }
                        ],
                    }
                )
            )
        return {"status": "success"}
    return {"status": "ignored"}


@router.get("/bus/history")
async def get_bus_history(
    _auth: dict = Depends(verify_api_key),
    bus_id: str = Query(..., min_length=1),
    minutes: int = Query(default=30, le=1440),
    db: AsyncSession = Depends(get_db),
):
    """Obtiene el historial de posiciones de un bus en los últimos N minutos."""
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    result = await db.execute(
        select(
            models.BusPosition.bus_id,
            func.ST_Y(models.BusPosition.geom).label("lat"),
            func.ST_X(models.BusPosition.geom).label("lon"),
            models.BusPosition.speed,
            models.BusPosition.recorded_at,
        )
        .where(
            and_(
                models.BusPosition.bus_id == bus_id,
                models.BusPosition.recorded_at >= since,
            )
        )
        .order_by(models.BusPosition.recorded_at.asc())
        .limit(2000)
    )
    positions = [
        {
            "lat": r.lat,
            "lon": r.lon,
            "speed": r.speed,
            "time": r.recorded_at.isoformat(),
        }
        for r in result
    ]
    return {
        "bus_id": bus_id,
        "minutes": minutes,
        "count": len(positions),
        "positions": positions,
    }


@router.get("/bus/active")
async def get_active_buses(
    _auth: dict = Depends(verify_api_key),
    minutes: int = Query(default=5, le=60),
    db: AsyncSession = Depends(get_db),
):
    """Lista buses activos en los últimos N minutos."""
    since = datetime.now(UTC) - timedelta(minutes=minutes)
    subq = (
        select(
            models.BusPosition.bus_id,
            func.max(models.BusPosition.recorded_at).label("last_seen"),
        )
        .where(models.BusPosition.recorded_at >= since)
        .group_by(models.BusPosition.bus_id)
        .subquery()
    )

    result = await db.execute(
        select(
            models.BusPosition.bus_id,
            func.ST_Y(models.BusPosition.geom).label("lat"),
            func.ST_X(models.BusPosition.geom).label("lon"),
            models.BusPosition.speed,
            subq.c.last_seen,
        )
        .join(
            subq,
            and_(
                models.BusPosition.bus_id == subq.c.bus_id,
                models.BusPosition.recorded_at == subq.c.last_seen,
            ),
        )
        .order_by(models.BusPosition.bus_id)
    )
    buses = [
        {
            "bus_id": r.bus_id,
            "lat": r.lat,
            "lon": r.lon,
            "speed": round(r.speed, 1),
            "last_seen": r.last_seen.isoformat(),
        }
        for r in result
    ]
    return {"active_count": len(buses), "buses": buses}


@router.get("/alert/geofence")
async def check_geofence(
    _auth: dict = Depends(verify_api_key),
    bus_id: str = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
    max_distance_meters: float = Query(default=200.0, le=5000.0),
    db: AsyncSession = Depends(get_db),
):
    """Verifica si un bus está dentro de la geocerca de alguna ruta."""
    point = f"SRID=4326;POINT({lon} {lat})"
    result = await db.execute(
        select(
            models.Route.id,
            models.Route.name,
            func.ST_Distance(
                models.Route.geom, func.ST_GeomFromText(point, 4326)
            ).label("distance"),
        )
        .where(
            func.ST_DWithin(
                models.Route.geom,
                func.ST_GeomFromText(point, 4326),
                max_distance_meters,
            )
        )
        .order_by("distance")
        .limit(1)
    )
    row = result.first()
    if row:
        return {
            "bus_id": bus_id,
            "status": "on_route",
            "route_name": row.name,
            "route_id": row.id,
            "distance_m": round(row.distance, 1),
        }
    return {
        "bus_id": bus_id,
        "status": "off_route",
        "alert": f"Bus fuera de ruta (>{max_distance_meters}m)",
    }


@router.get("/eta")
async def estimate_eta(
    _auth: dict = Depends(verify_api_key),
    bus_id: str = Query(...),
    stop_id: int = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Estima tiempo de llegada a una parada basado en la última posición y velocidad."""
    # Última posición del bus
    last_pos = await db.execute(
        select(
            func.ST_Y(models.BusPosition.geom).label("lat"),
            func.ST_X(models.BusPosition.geom).label("lon"),
            models.BusPosition.speed,
            models.BusPosition.recorded_at,
        )
        .where(models.BusPosition.bus_id == bus_id)
        .order_by(desc(models.BusPosition.recorded_at))
        .limit(1)
    )
    pos = last_pos.first()
    if not pos:
        return JSONResponse(
            status_code=404, content={"detail": "Bus sin datos recientes"}
        )

    # Posición de la parada
    stop = await db.execute(
        select(
            func.ST_Y(models.Stop.geom).label("lat"),
            func.ST_X(models.Stop.geom).label("lon"),
            models.Stop.name,
        ).where(models.Stop.id == stop_id)
    )
    stop_row = stop.first()
    if not stop_row:
        return JSONResponse(
            status_code=404, content={"detail": "Parada no encontrada"}
        )

    # Distancia (Haversine simplificada)
    earth_radius_m = 6371000
    dlat = math.radians(stop_row.lat - pos.lat)
    dlon = math.radians(stop_row.lon - pos.lon)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(pos.lat))
        * math.cos(math.radians(stop_row.lat))
        * math.sin(dlon / 2) ** 2
    )
    distance_m = earth_radius_m * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    speed_ms = (
        max(pos.speed / 3.6, 2.78) if pos.speed > 0 else 8.33
    )  # min 10 km/h, default 30 km/h
    eta_seconds = distance_m / speed_ms
    eta_minutes = round(eta_seconds / 60, 1)

    time_diff = (
        (datetime.now(UTC) - pos.recorded_at).total_seconds()
        if pos.recorded_at
        else 0
    )

    return {
        "bus_id": bus_id,
        "stop_id": stop_id,
        "stop_name": stop_row.name,
        "distance_m": round(distance_m, 1),
        "eta_minutes": eta_minutes,
        "speed_kmh": round(speed_ms * 3.6, 1),
        "last_position_age_seconds": round(time_diff, 1),
    }