"""
OptiBus B2B Middleware — DevSecOps v5.0
Middleware multi-tenant estricto para endpoints de cooperativa.
Inyecta cooperative_id en request.state y verifica pertenencia.
"""

import logging

from fastapi import HTTPException, Request, status

logger = logging.getLogger("optibus-b2b-middleware")


async def extract_cooperative_id(request: Request) -> int | None:
    """Extrae el cooperative_id del request.state (inyectado por el JWT)."""
    return getattr(request.state, "cooperative_id", None)


def require_cooperative_id(cooperative_id: int | None) -> int:
    """Valida que el cooperative_id exista. Lanza 403 si no está autenticado."""
    if cooperative_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso restringido: cooperativa no identificada.",
        )
    return cooperative_id


def verify_cooperative_role(auth_payload: dict, required_roles: list[str]) -> bool:
    """Verifica que el usuario autenticado tenga uno de los roles requeridos."""
    role = auth_payload.get("role", "public")
    return role in required_roles
</content>

<write_to_file>
<path>backend/b2b_routes.py</path>
<content>
"""
OptiBus B2B Dashboard Routes — DevSecOps v5.0
Endpoints protegidos para cooperativas: dashboard, geocercas, infracciones.
"""

import logging
from datetime import UTC, datetime, timedelta

import models
from auth_utils import verify_api_key
from database import get_db
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import JSONResponse
from geoalchemy2.types import Geography
from sqlalchemy import cast, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("optibus-b2b-routes")

router = APIRouter(prefix="/api/b2b", tags=["b2b"])


async def _get_cooperative(request: Request, _auth: dict, db: AsyncSession) -> int:
    """Obtiene el cooperative_id del JWT autenticado."""
    auth = _auth
    if isinstance(auth, dict) and auth.get("auth_type") == "jwt":
        coop_id = auth.get("cooperative_id")
        if coop_id is not None:
            return int(coop_id)
    if isinstance(auth, dict) and auth.get("auth_type") == "api_key":
        return 0
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Autenticación B2B requerida (JWT con cooperative_id)",
    )


@router.get("/dashboard")
async def dashboard(
    request: Request,
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Panel de control: buses activos, rutas, conductores."""
    coop_id = await _get_cooperative(request, _auth, db)

    since = datetime.now(UTC) - timedelta(minutes=5)
    active_query = select(
        func.count(func.distinct(models.BusPosition.bus_id))
    ).where(
        models.BusPosition.cooperative_id == coop_id,
        models.BusPosition.recorded_at >= since,
    )
    active_result = await db.execute(active_query)
    active_buses = active_result.scalar() or 0

    routes_query = select(func.count(models.Route.id)).where(
        models.Route.cooperative_id == coop_id
    )
    total_routes = (await db.execute(routes_query)).scalar() or 0

    stops_query = select(func.count(models.Stop.id)).where(
        models.Stop.cooperative_id == coop_id
    )
    total_stops = (await db.execute(stops_query)).scalar() or 0

    drivers_query = select(func.count(models.Driver.id)).where(
        models.Driver.cooperative_id == coop_id,
        models.Driver.is_active.is_(True),
    )
    active_drivers = (await db.execute(drivers_query)).scalar() or 0

    return {
        "cooperative_id": coop_id,
        "active_buses": active_buses,
        "total_routes": total_routes,
        "total_stops": total_stops,
        "active_drivers": active_drivers,
    }


@router.get("/fleet")
async def fleet_status(
    request: Request,
    _auth: dict = Depends(verify_api_key),
    minutes: int = Query(default=5, le=60),
    db: AsyncSession = Depends(get_db),
):
    """Estado de la flota con última posición y velocidad."""
    coop_id = await _get_cooperative(request, _auth, db)

    since = datetime.now(UTC) - timedelta(minutes=minutes)
    subq = (
        select(
            models.BusPosition.bus_id,
            func.max(models.BusPosition.recorded_at).label("last_seen"),
        )
        .where(
            models.BusPosition.cooperative_id == coop_id,
            models.BusPosition.recorded_at >= since,
        )
        .group_by(models.BusPosition.bus_id)
        .subquery()
    )

    result = await db.execute(
        select(
            models.BusPosition.bus_id,
            func.ST_Y(models.BusPosition.geom).label("lat"),
            func.ST_X(models.BusPosition.geom).label("lon"),
            models.BusPosition.speed,
            models.BusPosition.route_id,
            subq.c.last_seen,
        )
        .join(
            subq,
            (models.BusPosition.bus_id == subq.c.bus_id)
            & (models.BusPosition.recorded_at == subq.c.last_seen),
        )
        .order_by(models.BusPosition.bus_id)
    )

    fleet = []
    for r in result:
        fleet.append({
            "bus_id": r.bus_id,
            "lat": round(r.lat, 6) if r.lat else None,
            "lon": round(r.lon, 6) if r.lon else None,
            "speed_kmh": round(r.speed, 1),
            "route_id": r.route_id,
            "last_seen": r.last_seen.isoformat(),
            "status": "active" if r.last_seen else "inactive",
        })

    return {"cooperative_id": coop_id, "fleet_size": len(fleet), "fleet": fleet}


@router.get("/geofence/alerts")
async def geofence_alerts(
    request: Request,
    _auth: dict = Depends(verify_api_key),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Historial de alertas de geocerca."""
    coop_id = await _get_cooperative(request, _auth, db)

    result = await db.execute(
        select(models.GeofenceAlert)
        .where(models.GeofenceAlert.cooperative_id == coop_id)
        .order_by(desc(models.GeofenceAlert.created_at))
        .limit(limit)
    )
    alerts = [
        {
            "id": a.id,
            "bus_id": a.bus_id,
            "route_id": a.route_id,
            "alert_type": a.alert_type,
            "message": a.message,
            "created_at": a.created_at.isoformat() if a.created_at else None,
        }
        for a in result
    ]
    return {"cooperative_id": coop_id, "alerts": alerts}


@router.get("/infractions")
async def infractions_list(
    request: Request,
    _auth: dict = Depends(verify_api_key),
    limit: int = Query(default=20, le=100),
    db: AsyncSession = Depends(get_db),
):
    """Reporte de infracciones: excesos de velocidad, desvíos."""
    coop_id = await _get_cooperative(request, _auth, db)

    result = await db.execute(
        select(models.Infraction)
        .where(models.Infraction.cooperative_id == coop_id)
        .order_by(desc(models.Infraction.recorded_at))
        .limit(limit)
    )
    infractions = [
        {
            "id": i.id,
            "bus_id": i.bus_id,
            "driver_id": i.driver_id,
            "infraction_type": i.infraction_type,
            "speed_kmh": round(i.speed_kmh, 1),
            "max_allowed_kmh": round(i.max_allowed_kmh, 1),
            "location": (
                {"lat": round(i.lat, 6), "lon": round(i.lon, 6)}
                if i.lat and i.lon else None
            ),
            "recorded_at": i.recorded_at.isoformat() if i.recorded_at else None,
        }
        for i in result
    ]
    return {"cooperative_id": coop_id, "infractions": infractions}


@router.post("/geofence/check")
async def check_geofence_b2b(
    request: Request,
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Verifica geocerca para un bus específico."""
    coop_id = await _get_cooperative(request, _auth, db)
    body = await request.json()
    bus_id = body.get("bus_id")
    lat = body.get("lat")
    lon = body.get("lon")
    route_id = body.get("route_id")
    max_distance = body.get("max_distance_meters", 200)

    if not bus_id or lat is None or lon is None:
        return JSONResponse(status_code=400, content={"detail": "bus_id, lat, lon requeridos"})

    point = f"SRID=4326;POINT({lon} {lat})"

    route_query = select(
        models.Route.id,
        models.Route.name,
        func.ST_Distance(
            cast(models.Route.geom, Geography),
            cast(func.ST_GeomFromText(point, 4326), Geography),
        ).label("distance"),
    ).where(
        models.Route.cooperative_id == coop_id,
        func.ST_DWithin(
            cast(models.Route.geom, Geography),
            cast(func.ST_GeomFromText(point, 4326), Geography),
            max_distance,
        ),
    ).order_by("distance").limit(1)

    route_result = await db.execute(route_query)
    route = route_result.first()

    if not route:
        alert = models.GeofenceAlert(
            cooperative_id=coop_id,
            bus_id=bus_id,
            route_id=route_id,
            alert_type="off_route",
            message=f"Bus {bus_id} fuera de ruta a {max_distance}m",
        )
        db.add(alert)
        await db.commit()
        return {"bus_id": bus_id, "status": "off_route", "alert": f"Bus fuera de ruta (>{max_distance}m)"}

    return {"bus_id": bus_id, "status": "on_route", "route_name": route.name, "distance_m": round(route.distance, 1)}


@router.post("/infractions/report-speed")
async def report_speed_infraction(
    request: Request,
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Registra una infracción por exceso de velocidad."""
    coop_id = await _get_cooperative(request, _auth, db)
    body = await request.json()
    bus_id = body.get("bus_id")
    driver_id = body.get("driver_id")
    speed_kmh = body.get("speed_kmh")
    max_allowed = body.get("max_allowed_kmh", 60)
    lat = body.get("lat")
    lon = body.get("lon")

    if not bus_id or speed_kmh is None:
        return JSONResponse(status_code=400, content={"detail": "bus_id y speed_kmh requeridos"})

    infraction = models.Infraction(
        cooperative_id=coop_id,
        bus_id=bus_id,
        driver_id=driver_id,
        infraction_type="speeding",
        speed_kmh=speed_kmh,
        max_allowed_kmh=max_allowed,
        lat=lat,
        lon=lon,
        recorded_at=datetime.now(UTC),
    )
    db.add(infraction)
    await db.commit()

    logger.warning(f"Infracción: {bus_id} a {speed_kmh} km/h (máx {max_allowed})")
    return {"status": "recorded", "infraction_id": infraction.id}