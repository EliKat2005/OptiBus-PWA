"""
OptiBus Route Routes — DevSecOps v4.0
Endpoints de rutas, paradas, upload GPX, planificador de viajes.
Separado de main.py para mantener modularidad.
"""

import json
import logging
import os
import re
from datetime import UTC, datetime
from pathlib import Path

import aiofiles
import gpxpy
import models
from auth_utils import verify_api_key, verify_optional_auth, require_admin
from config import (
    BUS_ID_PATTERN,
    MAX_GPX_UPLOAD_MB,
    SAFE_ROUTE_NAME_PATTERN,
    get_recorded_routes_dir,
)
from database import get_db
from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    Query,
    Request,
    UploadFile,
)
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import and_, cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from geoalchemy2.types import Geography
from utils.gps_cleaner import clean_gps_track
from ws_manager import ConnectionManager

logger = logging.getLogger("optibus-route-routes")

router = APIRouter(prefix="/api", tags=["routes"])

# WebSocket manager (inyectado desde main.py)
_ws_manager: ConnectionManager | None = None


def init_route_routes(ws_manager: ConnectionManager):
    """Inicializa el módulo con el ConnectionManager."""
    global _ws_manager
    _ws_manager = ws_manager


# ── Helper para caching Redis ──


async def _get_redis():
    """Obtiene cliente Redis con manejo de errores."""
    from rate_limiter import get_redis

    return await get_redis()


# ── Endpoints ──


@router.get("/routes")
async def get_routes(db: AsyncSession = Depends(get_db)):
    """Obtiene todas las rutas con paradas. Cacheado en Redis por 60s."""
    redis = await _get_redis()
    if redis:
        try:
            cached = await redis.get("cache:routes")
            if cached:
                logger.debug("Routes cache HIT (Redis)")
                return json.loads(cached)
        except Exception as e:
            logger.debug(f"Redis cache miss: {e}")

    result = await db.execute(
        select(
            models.Route.id,
            models.Route.name,
            func.ST_AsGeoJSON(models.Route.geom).label("route_geojson"),
        ).order_by(models.Route.id)
    )
    route_rows = result.all()

    route_ids = [row.id for row in route_rows]
    stops_by_route: dict = {rid: [] for rid in route_ids}
    if route_ids:
        stops_result = await db.execute(
            select(
                models.Stop.id,
                models.Stop.name,
                models.Stop.route_id,
                func.coalesce(models.Stop.lat, func.ST_Y(models.Stop.geom)).label(
                    "lat"
                ),
                func.coalesce(models.Stop.lon, func.ST_X(models.Stop.geom)).label(
                    "lon"
                ),
            )
            .where(models.Stop.route_id.in_(route_ids))
            .order_by(models.Stop.id)
        )
        for stop in stops_result:
            if stop.route_id in stops_by_route:
                stops_by_route[stop.route_id].append(
                    {
                        "id": stop.id,
                        "name": stop.name,
                        "lat": round(stop.lat, 7),
                        "lon": round(stop.lon, 7),
                    }
                )

    features = []
    for row in route_rows:
        features.append(
            {
                "type": "Feature",
                "properties": {
                    "id": row.id,
                    "name": row.name,
                    "stops": stops_by_route.get(row.id, []),
                },
                "geometry": json.loads(row.route_geojson),
            }
        )

    response = {"type": "FeatureCollection", "features": features}

    if redis:
        try:
            await redis.setex("cache:routes", 60, json.dumps(response, default=str))
        except Exception:
            pass

    return response


@router.get("/stops/nearby")
async def get_nearby_stops(
    lat: float,
    lon: float,
    radius_meters: float = 300.0,
    max_results: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db),
):
    """Obtiene paradas cercanas a unas coordenadas."""
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return JSONResponse(
            status_code=400, content={"detail": "Coordenadas inválidas."}
        )
    if radius_meters > 10000:
        return JSONResponse(
            status_code=400, content={"detail": "Radio máximo: 10000 metros."}
        )

    point = f"SRID=4326;POINT({lon} {lat})"
    query = (
        select(
            models.Stop.id,
            models.Stop.name,
            func.ST_AsGeoJSON(models.Stop.geom).label("geojson"),
            func.ST_DistanceSphere(
                cast(models.Stop.geom, Geography),
                cast(func.ST_GeomFromText(point, 4326), Geography),
            ).label("distance"),
        )
        .where(
            func.ST_DWithin(
                cast(models.Stop.geom, Geography),
                cast(func.ST_GeomFromText(point, 4326), Geography),
                radius_meters,
            )
        )
        .order_by("distance")
        .limit(max_results)
    )

    result = await db.execute(query)
    stops = [
        {
            "id": r.id,
            "name": r.name,
            "distance": round(r.distance, 2),
            "geometry": json.loads(r.geojson),
        }
        for r in result
    ]
    return {"radius_meters": radius_meters, "nearby_stops": stops}


@router.post("/routes/upload")
async def upload_recorded_route(
    _auth: dict = Depends(verify_api_key),
    gpx_file: UploadFile = File(..., max_size=MAX_GPX_UPLOAD_MB * 1024 * 1024),
    stops_json: str = Form(...),
    company: str = Form(default=""),
    route_name: str = Form(...),
    tags: str = Form(default=""),
    max_speed_kmh: float = Form(default=120.0),
    db: AsyncSession = Depends(get_db),
):
    """Recibe una ruta grabada desde el APK."""
    safe_route_name = re.sub(
        r"[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ _\-]", "", route_name
    ).strip()
    if not safe_route_name:
        raise HTTPException(status_code=400, detail="Nombre de ruta inválido")

    try:
        gpx_content = await gpx_file.read()
        gpx = gpxpy.parse(gpx_content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(
            status_code=400, detail=f"Error parseando GPX: {e}"
        ) from e

    raw_points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                iso_time = (
                    point.time.isoformat() + "Z" if point.time else ""
                )
                raw_points.append(
                    (point.latitude, point.longitude, iso_time)
                )

    if len(raw_points) < 2:
        raise HTTPException(
            status_code=400, detail="Se requieren al menos 2 puntos GPS"
        )

    raw_points.sort(key=lambda p: p[2])
    cleaned_points = clean_gps_track(raw_points, max_speed_kmh=max_speed_kmh)
    removed = len(raw_points) - len(cleaned_points)

    if removed > 0:
        logger.info(
            f"GPS cleaner eliminó {removed} de {len(raw_points)} puntos"
        )

    if len(cleaned_points) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"Después de limpiar solo quedaron {len(cleaned_points)} puntos.",
        )

    wkt_coords = [f"{lon} {lat}" for lat, lon, _ in cleaned_points]
    linestring_wkt = f"SRID=4326;LINESTRING({', '.join(wkt_coords)})"
    new_route = models.Route(name=safe_route_name, geom=linestring_wkt)
    db.add(new_route)
    await db.flush()

    stops_count = 0
    try:
        stops_data = json.loads(stops_json)
        if isinstance(stops_data, list):
            for stop in stops_data:
                if isinstance(stop, dict) and "lat" in stop and "lon" in stop:
                    stop_name = stop.get(
                        "name", f"Parada {stops_count + 1}"
                    )
                    stop_point = (
                        f"SRID=4326;POINT({stop['lon']} {stop['lat']})"
                    )
                    db.add(
                        models.Stop(
                            name=str(stop_name)[:255],
                            route_id=new_route.id,
                            geom=stop_point,
                            lat=stop["lat"],
                            lon=stop["lon"],
                        )
                    )
                    stops_count += 1
    except json.JSONDecodeError:
        logger.warning("stops_json no es JSON válido")

    await db.commit()

    # Guardar copia de auditoría
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    base_filename = f"{safe_route_name.replace(' ', '_')}_{timestamp}"

    recorded_dir = get_recorded_routes_dir()
    gpx_path = recorded_dir / f"{base_filename}.gpx"
    async with aiofiles.open(gpx_path, "wb") as f:
        await f.write(gpx_content)

    total_points = len(cleaned_points)
    meta_path = recorded_dir / f"{base_filename}_meta.json"
    meta = {
        "route_name": safe_route_name,
        "company": company,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "points_raw": len(raw_points),
        "points_clean": total_points,
        "outliers_removed": removed,
        "stops_count": stops_count,
        "recorded_at": datetime.now(UTC).isoformat(),
        "route_id": new_route.id,
    }
    async with aiofiles.open(meta_path, "w") as f:
        await f.write(json.dumps(meta, indent=2, ensure_ascii=False))

    logger.info(
        f"Ruta '{safe_route_name}' subida: {total_points} puntos, {stops_count} paradas"
    )

    return {
        "status": "success",
        "route_id": new_route.id,
        "route_name": safe_route_name,
        "points_cleaned": total_points,
        "outliers_removed": removed,
        "stops": stops_count,
        "saved_files": [
            str(gpx_path.relative_to(Path(__file__).parent)),
            str(meta_path.relative_to(Path(__file__).parent)),
        ],
    }


@router.post("/stops/record")
async def record_stop(
    request: Request,
    _auth: dict = Depends(verify_api_key),
    db: AsyncSession = Depends(get_db),
):
    """Recibe una parada individual grabada desde el APK (tiempo real)."""
    body = await request.json()
    bus_id = body.get("bus_id", "unknown")
    stop_name = body.get("stop_name", "Parada")
    lat = body.get("lat")
    lon = body.get("lon")
    route_name = body.get("route_name", "")

    if lat is None or lon is None:
        return JSONResponse(
            status_code=400, content={"detail": "lat y lon requeridos"}
        )
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return JSONResponse(
            status_code=400, content={"detail": "Coordenadas inválidas"}
        )

    try:
        if route_name:
            result = await db.execute(
                select(models.Route)
                .where(models.Route.name == route_name)
                .limit(1)
            )
            route = result.scalar_one_or_none()
        else:
            route = None

        stop_point = f"SRID=4326;POINT({lon} {lat})"
        db.add(
            models.Stop(
                name=str(stop_name)[:255],
                route_id=route.id if route else None,
                geom=func.ST_GeomFromText(stop_point, 4326),
                lat=lat,
                lon=lon,
            )
        )
        await db.commit()

        logger.info(
            f"Parada '{stop_name}' registrada vía API (bus={bus_id})"
        )

        if _ws_manager:
            await _ws_manager.broadcast(
                json.dumps(
                    {
                        "type": "stop_recorded",
                        "stop": {
                            "name": stop_name,
                            "lat": lat,
                            "lon": lon,
                            "bus_id": bus_id,
                            "route_name": route_name,
                        },
                    }
                )
            )

        return {
            "status": "success",
            "stop_name": stop_name,
            "lat": lat,
            "lon": lon,
        }
    except Exception as e:
        logger.error(f"Error registrando parada: {e}")
        await db.rollback()
        return JSONResponse(
            status_code=500,
            content={"detail": f"Error guardando parada: {str(e)}"},
        )


@router.post("/routes/plan")
async def plan_route(
    request: Request,
    _auth: dict = Depends(verify_optional_auth),
    db: AsyncSession = Depends(get_db),
):
    """
    Planificador de viajes entre dos paradas.
    DevSecOps: Ahora requiere autenticación (opcional si API Key no está configurada).
    """
    body = await request.json()
    from_id = body.get("from_stop_id")
    to_id = body.get("to_stop_id")
    from_name = body.get("from_name")
    to_name = body.get("to_name")

    if (from_id is None and from_name) or (to_id is None and to_name):
        result = await db.execute(
            select(models.Stop.id, models.Stop.name).where(
                models.Stop.name.in_(
                    [from_name, to_name] if from_name and to_name else []
                )
            )
        )
        stops_by_name = {r.name: r.id for r in result}
        if from_name and from_id is None:
            from_id = stops_by_name.get(from_name)
        if to_name and to_id is None:
            to_id = stops_by_name.get(to_name)

    if from_id is None or to_id is None:
        return JSONResponse(
            status_code=400,
            content={
                "detail": "from_stop_id y to_stop_id requeridos (o nombres válidos)"
            },
        )

    if from_id == to_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Origen y destino son la misma parada"},
        )

    from_result = await db.execute(
        select(
            models.Stop.route_id,
            models.Route.name.label("route_name"),
            models.Stop.id.label("stop_id"),
            models.Stop.name.label("stop_name"),
        )
        .join(models.Route, models.Stop.route_id == models.Route.id)
        .where(models.Stop.id.in_([from_id, to_id]))
    )
    stop_routes: dict = {}
    for r in from_result:
        rid = r.route_id
        if rid not in stop_routes:
            stop_routes[rid] = {"route_name": r.route_name, "stops": {}}
        stop_routes[rid]["stops"][r.stop_id] = r.stop_name

    # Buscar ruta directa
    direct_route = None
    for route_id, data in stop_routes.items():
        if from_id in data["stops"] and to_id in data["stops"]:
            stops_order = await db.execute(
                select(models.Stop.id)
                .where(models.Stop.route_id == route_id)
                .order_by(models.Stop.id)
            )
            ordered = [s.id for s in stops_order]
            if from_id in ordered and to_id in ordered:
                pos_from = ordered.index(from_id)
                pos_to = ordered.index(to_id)
                if direct_route is None or abs(pos_to - pos_from) < direct_route.get(
                    "distance", 9999
                ):
                    direct_route = {
                        "route_id": route_id,
                        "route_name": data["route_name"],
                        "board_stop": data["stops"][from_id],
                        "alight_stop": data["stops"][to_id],
                        "stops_count": abs(pos_to - pos_from),
                        "direction": "forward" if pos_to > pos_from else "backward",
                    }

    if direct_route:
        return {
            "type": "direct",
            "plan": [direct_route],
            "total_stops": direct_route["stops_count"],
            "message": f"Toma la ruta '{direct_route['route_name']}' en '{direct_route['board_stop']}' y bájate en '{direct_route['alight_stop']}' ({direct_route['stops_count']} paradas)",
        }

    # Buscar transbordo
    from_routes = [
        rid for rid, data in stop_routes.items() if from_id in data["stops"]
    ]
    to_routes = [
        rid for rid, data in stop_routes.items() if to_id in data["stops"]
    ]

    if not from_routes or not to_routes:
        return JSONResponse(
            status_code=404,
            content={"detail": "No se encontraron rutas para estas paradas"},
        )

    for fr in from_routes:
        for tr in to_routes:
            if fr == tr:
                continue
            fr_stops = await db.execute(
                select(models.Stop.id, models.Stop.name).where(
                    models.Stop.route_id == fr
                )
            )
            fr_stop_set = {s.id: s.name for s in fr_stops}
            tr_stops = await db.execute(
                select(models.Stop.id, models.Stop.name).where(
                    models.Stop.route_id == tr
                )
            )
            tr_stop_set = {s.id: s.name for s in tr_stops}

            common = set(fr_stop_set.keys()) & set(tr_stop_set.keys())
            if common:
                transfer_stop_id = min(common)
                return {
                    "type": "transfer",
                    "plan": [
                        {
                            "route_id": fr,
                            "route_name": stop_routes[fr]["route_name"],
                            "board_stop": stop_routes[fr]["stops"][from_id],
                            "alight_stop": fr_stop_set[transfer_stop_id],
                            "transfer": True,
                        },
                        {
                            "route_id": tr,
                            "route_name": stop_routes[tr]["route_name"],
                            "board_stop": tr_stop_set[transfer_stop_id],
                            "alight_stop": stop_routes[tr]["stops"][to_id],
                            "transfer": False,
                        },
                    ],
                    "total_transfers": 1,
                    "transfer_stop": fr_stop_set[transfer_stop_id],
                    "message": f"Toma '{stop_routes[fr]['route_name']}' en '{stop_routes[fr]['stops'][from_id]}', transborda en '{fr_stop_set[transfer_stop_id]}', y toma '{stop_routes[tr]['route_name']}' hasta '{stop_routes[tr]['stops'][to_id]}'",
                }

    return JSONResponse(
        status_code=404,
        content={
            "detail": "No se encontró conexión entre estas paradas (sin transbordo común)"
        },
    )


@router.get("/simulator/status")
async def simulator_status(_auth: dict = Depends(verify_api_key)):
    """Estado del simulador de buses."""
    return {
        "simulator_enabled": os.environ.get(
            "ENABLE_BUS_SIMULATOR", "false"
        ).lower()
        == "true",
        "active_ws_connections": _ws_manager.active_count if _ws_manager else 0,
    }