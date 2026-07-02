"""
OptiBus Route Routes — DevSecOps v4.0
Endpoints de rutas, paradas, upload GPX, planificador de viajes.
Separado de main.py para mantener modularidad.
"""

import json
import logging
import os
import re
from datetime import UTC, datetime, timedelta
from pathlib import Path

import aiofiles
import gpxpy
import models
from auth_utils import verify_api_key, verify_optional_auth
from config import (
    MAX_GPX_UPLOAD_MB,
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
from geoalchemy2.types import Geography
from sqlalchemy import cast, func, select
from sqlalchemy.ext.asyncio import AsyncSession
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


@router.get("/stops/search")
async def search_stops(
    q: str = Query(..., min_length=1, max_length=100),
    max_results: int = Query(default=8, le=20),
    db: AsyncSession = Depends(get_db),
):
    """Búsqueda de paradas por nombre parcial (autocompletado)."""
    search_term = f"%{q.strip()}%"
    result = await db.execute(
        select(
            models.Stop.id,
            models.Stop.name,
            models.Stop.route_id,
            models.Route.name.label("route_name"),
            func.coalesce(models.Stop.lat, func.ST_Y(models.Stop.geom)).label("lat"),
            func.coalesce(models.Stop.lon, func.ST_X(models.Stop.geom)).label("lon"),
        )
        .join(models.Route, models.Stop.route_id == models.Route.id, isouter=True)
        .where(models.Stop.name.ilike(search_term))
        .order_by(models.Stop.name)
        .limit(max_results)
    )
    stops = [
        {
            "id": r.id,
            "name": r.name,
            "route_id": r.route_id,
            "route_name": r.route_name or "",
            "lat": round(r.lat, 7) if r.lat else None,
            "lon": round(r.lon, 7) if r.lon else None,
        }
        for r in result
    ]
    return {"query": q, "results": stops}


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
            func.ST_Distance(
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
    Planificador de viajes profesional con BFS multi-transbordo (hasta 2 transbordos).
    DevSecOps: Autenticación opcional.
    """
    body = await request.json()
    from_id = body.get("from_stop_id")
    to_id = body.get("to_stop_id")
    from_name = body.get("from_name")
    to_name = body.get("to_name")

    # ── Resolver nombres a IDs si es necesario ──
    if (from_id is None and from_name) or (to_id is None and to_name):
        names_to_search = []
        if from_name and from_id is None:
            names_to_search.append(from_name)
        if to_name and to_id is None:
            names_to_search.append(to_name)
        result = await db.execute(
            select(models.Stop.id, models.Stop.name).where(
                models.Stop.name.in_(names_to_search) if names_to_search else True
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
            content={"detail": "Selecciona una parada de origen y una de destino de las sugerencias."},
        )

    if from_id == to_id:
        return JSONResponse(
            status_code=400,
            content={"detail": "Origen y destino son la misma parada."},
        )

    # ── Cargar TODAS las rutas y sus paradas en una sola consulta ──
    all_stops_result = await db.execute(
        select(
            models.Stop.id,
            models.Stop.name,
            models.Stop.route_id,
            models.Route.name.label("route_name"),
        )
        .join(models.Route, models.Stop.route_id == models.Route.id, isouter=True)
        .order_by(models.Stop.id)
    )
    # route_to_stops: {route_id: {stop_id: stop_name, ...}}
    # stop_to_routes: {stop_id: {route_id: route_name, ...}}
    route_to_stops: dict = {}
    stop_to_routes: dict = {}
    route_names: dict = {}
    stop_names: dict = {}
    for r in all_stops_result:
        rid = r.route_id
        sid = r.id
        if rid is None:
            stop_names[sid] = r.name
            continue  # Stops sin ruta: solo guardar nombre, no incluir en grafo
        if rid not in route_to_stops:
            route_to_stops[rid] = {}
            route_names[rid] = r.route_name
        route_to_stops[rid][sid] = r.name
        if sid not in stop_to_routes:
            stop_to_routes[sid] = {}
            stop_names[sid] = r.name
        stop_to_routes[sid][rid] = r.route_name

    if not route_to_stops:
        return JSONResponse(
            status_code=404,
            content={"detail": "No hay rutas configuradas en el sistema."},
        )

    # ── Búsqueda: Ruta directa ──
    direct = _find_direct_route(from_id, to_id, route_to_stops, route_names, stop_names)
    if direct:
        return {
            "type": "direct",
            "plan": [direct],
            "total_stops": direct["stops_count"],
            "total_transfers": 0,
            "message": f"🚌 Ruta directa: Toma '{direct['route_name']}' en '{direct['board_stop']}' y bájate en '{direct['alight_stop']}' ({direct['stops_count']} paradas).",
        }

    # ── BFS para 1 o 2 transbordos ──
    bfs_result = _bfs_find_route(
        from_id, to_id, route_to_stops, stop_to_routes, route_names, stop_names, max_transfers=2
    )
    if bfs_result:
        plan_steps = []
        for step in bfs_result:
            plan_steps.append(step)
        message_parts = []
        for i, step in enumerate(bfs_result):
            if i == 0:
                message_parts.append(f"Toma '{step['route_name']}' en '{step['board_stop']}'")
            else:
                message_parts.append(f"transborda a '{step['route_name']}' en '{step['board_stop']}'")
            if i == len(bfs_result) - 1:
                message_parts[-1] += f" y bájate en '{step['alight_stop']}'"
            else:
                message_parts[-1] += f" hasta '{step['alight_stop']}'"
        return {
            "type": "transfer",
            "plan": bfs_result,
            "total_transfers": len(bfs_result) - 1,
            "message": " → ".join(message_parts) + ".",
        }

    # ── Sin ruta: sugerir alternativas ──
    alternatives = await _find_alternatives(from_id, to_id, db)
    return JSONResponse(
        status_code=404,
        content={
            "detail": "No se encontró ruta entre estas paradas.",
            "alternatives": alternatives,
        },
    )


def _find_direct_route(
    from_id: int, to_id: int,
    route_to_stops: dict, route_names: dict, stop_names: dict
) -> dict | None:
    """Encuentra ruta directa si ambas paradas comparten alguna ruta."""
    best = None
    for rid, stops in route_to_stops.items():
        if from_id in stops and to_id in stops:
            ordered = list(stops.keys())
            if from_id in ordered and to_id in ordered:
                pos_from = ordered.index(from_id)
                pos_to = ordered.index(to_id)
                count = abs(pos_to - pos_from)
                if best is None or count < best.get("stops_count", 9999):
                    best = {
                        "route_id": rid,
                        "route_name": route_names[rid],
                        "board_stop": stop_names.get(from_id, stops[from_id]),
                        "alight_stop": stop_names.get(to_id, stops[to_id]),
                        "stops_count": count,
                        "direction": "forward" if pos_to > pos_from else "backward",
                    }
    return best


def _bfs_find_route(
    from_id: int, to_id: int,
    route_to_stops: dict, stop_to_routes: dict,
    route_names: dict, stop_names: dict,
    max_transfers: int = 2
) -> list[dict] | None:
    """
    BFS sobre el grafo de rutas. Cada estado es (stop_id, route_id, path).
    max_transfers = número máximo de cambios de ruta.
    """
    from collections import deque

    # Obtener rutas del origen
    from_routes = list(stop_to_routes.get(from_id, {}).keys())
    if not from_routes:
        return None

    # Cola BFS: (current_stop_id, current_route_id, transfers_count, path_steps)
    queue = deque()
    visited = set()

    for rid in from_routes:
        queue.append((from_id, rid, 0, []))
        visited.add((from_id, rid))

    while queue:
        stop_id, route_id, transfers, path = queue.popleft()

        # Si esta ruta contiene la parada destino
        if to_id in route_to_stops.get(route_id, {}):
            ordered = list(route_to_stops[route_id].keys())
            if stop_id in ordered and to_id in ordered:
                # Construir el plan final
                final_path = list(path)
                final_path.append({
                    "route_id": route_id,
                    "route_name": route_names[route_id],
                    "board_stop": stop_names.get(stop_id, str(stop_id)),
                    "alight_stop": stop_names.get(to_id, str(to_id)),
                    "stops_count": abs(ordered.index(to_id) - ordered.index(stop_id)),
                })
                return final_path

        # Si ya alcanzamos el máximo de transbordos, no expandir más
        if transfers >= max_transfers:
            continue

        # Expandir: desde cada parada de esta ruta, cambiar a otras rutas
        for next_stop_id in route_to_stops.get(route_id, {}):
            for next_route_id in stop_to_routes.get(next_stop_id, {}):
                if next_route_id == route_id:
                    continue
                state = (next_stop_id, next_route_id)
                if state not in visited:
                    visited.add(state)
                    new_path = list(path)
                    if new_path:
                        # Actualizar el último paso con la parada de bajada
                        new_path[-1]["alight_stop"] = stop_names.get(next_stop_id, str(next_stop_id))
                    new_path.append({
                        "route_id": next_route_id,
                        "route_name": route_names[next_route_id],
                        "board_stop": stop_names.get(next_stop_id, str(next_stop_id)),
                        "alight_stop": "",  # Se completa después
                        "stops_count": 0,
                    })
                    queue.append((next_stop_id, next_route_id, transfers + 1, new_path))

    return None


async def _find_alternatives(from_id: int, to_id: int, db: AsyncSession) -> list[dict]:
    """Busca paradas alternativas cercanas al origen/destino."""
    alternatives = []
    for stop_id, label in [(from_id, "origen"), (to_id, "destino")]:
        stop_result = await db.execute(
            select(
                func.coalesce(models.Stop.lat, func.ST_Y(models.Stop.geom)).label("lat"),
                func.coalesce(models.Stop.lon, func.ST_X(models.Stop.geom)).label("lon"),
            ).where(models.Stop.id == stop_id)
        )
        stop_row = stop_result.first()
        if not stop_row or not stop_row.lat or not stop_row.lon:
            continue
        nearby = await db.execute(
            select(
                models.Stop.id,
                models.Stop.name,
                models.Route.name.label("route_name"),
                func.ST_Distance(
                    cast(models.Stop.geom, Geography),
                    cast(func.ST_GeomFromText(f"SRID=4326;POINT({stop_row.lon} {stop_row.lat})", 4326), Geography),
                ).label("distance"),
            )
            .join(models.Route, models.Stop.route_id == models.Route.id, isouter=True)
            .where(
                models.Stop.id != stop_id,
                func.ST_DWithin(
                    cast(models.Stop.geom, Geography),
                    cast(func.ST_GeomFromText(f"SRID=4326;POINT({stop_row.lon} {stop_row.lat})", 4326), Geography),
                    500,
                ),
            )
            .order_by("distance")
            .limit(5)
        )
        for n in nearby:
            alternatives.append({
                "type": f"cerca_de_{label}",
                "original_stop_id": stop_id,
                "alternative_stop_id": n.id,
                "alternative_name": n.name,
                "route_name": n.route_name or "",
                "distance_m": round(n.distance, 1),
            })
    return alternatives


@router.get("/stops/{stop_id}/eta")
async def stop_eta(
    stop_id: int,
    db: AsyncSession = Depends(get_db),
):
    """
    Público: Calcula ETA a una parada basado en el bus más cercano.
    Usa ST_Distance de PostGIS para distancia precisa y velocidad actual del bus.
    Retorna IDs ofuscados con hashids.
    """
    # Posición de la parada
    stop_query = await db.execute(
        select(
            func.coalesce(models.Stop.lat, func.ST_Y(models.Stop.geom)).label("lat"),
            func.coalesce(models.Stop.lon, func.ST_X(models.Stop.geom)).label("lon"),
            models.Stop.name,
        ).where(models.Stop.id == stop_id)
    )
    stop_row = stop_query.first()
    if not stop_row or not stop_row.lat:
        return JSONResponse(status_code=404, content={"detail": "Parada no encontrada"})

    stop_point = f"SRID=4326;POINT({stop_row.lon} {stop_row.lat})"

    # Bus más cercano activo (últimos 3 minutos)
    since = datetime.now(UTC) - timedelta(minutes=3)
    nearest_query = (
        select(
            models.BusPosition.bus_id,
            func.ST_Y(models.BusPosition.geom).label("bus_lat"),
            func.ST_X(models.BusPosition.geom).label("bus_lon"),
            models.BusPosition.speed,
            models.BusPosition.recorded_at,
            func.ST_Distance(
                models.BusPosition.geom,
                func.ST_GeomFromText(stop_point, 4326),
            ).label("distance_m"),
        )
        .where(models.BusPosition.recorded_at >= since)
        .order_by("distance_m")
        .limit(1)
    )
    nearest_result = await db.execute(nearest_query)
    bus = nearest_result.first()

    if not bus:
        return {
            "stop_id": stop_id,
            "stop_name": stop_row.name,
            "eta_minutes": None,
            "message": "No hay buses activos cerca de esta parada",
        }

    # Calcular ETA
    distance_m = bus.distance_m or 0
    speed_kmh = max(bus.speed or 0, 5)  # mínimo 5 km/h para evitar división por cero
    speed_ms = speed_kmh / 3.6
    eta_seconds = distance_m / speed_ms if speed_ms > 0 else 0
    eta_minutes = round(eta_seconds / 60, 1)

    return {
        "stop_id": stop_id,
        "stop_name": stop_row.name,
        "bus_id": bus.bus_id,
        "distance_m": round(distance_m, 1),
        "speed_kmh": round(speed_kmh, 1),
        "eta_minutes": eta_minutes,
        "last_position_at": bus.recorded_at.isoformat() if bus.recorded_at else None,
    }


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
