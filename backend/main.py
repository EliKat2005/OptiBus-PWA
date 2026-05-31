from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, Request, HTTPException, status, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, HTMLResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
from contextlib import asynccontextmanager
from database import engine, Base, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast, and_, desc
from geoalchemy2.types import Geography
from prometheus_fastapi_instrumentator import Instrumentator
from fastapi import UploadFile, File, Form
import models
import asyncio
import json
import logging
import os
import time
import re
from collections import defaultdict
from secrets import compare_digest
from datetime import datetime, timezone, timedelta
import redis.asyncio as aioredis
import math
import gpxpy
import aiofiles
from pathlib import Path
from gps_cleaner import clean_gps_track

# --- Logging estructurado ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("optibus-api")

# --- Redis para rate limiting distribuido ---
REDIS_URL = os.getenv("REDIS_URL", "redis://redis:6379/0")
redis_client: aioredis.Redis | None = None

async def get_redis() -> aioredis.Redis | None:
    global redis_client
    if redis_client is None:
        try:
            redis_client = aioredis.from_url(REDIS_URL, encoding="utf-8", decode_responses=True)
            await redis_client.ping()
            logger.info("Conectado a Redis para rate limiting distribuido")
        except Exception as e:
            logger.warning(f"Redis no disponible, usando rate limiter en memoria: {e}")
            redis_client = False  # type: ignore
    return redis_client if redis_client is not False else None

class DistributedRateLimiter:
    """Rate limiter con fallback a memoria si Redis no está disponible."""
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.fallback_clients: dict[str, list[float]] = defaultdict(list)

    async def is_allowed(self, client_ip: str) -> bool:
        r = await get_redis()
        if r:
            key = f"rl:{client_ip}"
            current = await r.incr(key)
            if current == 1:
                await r.expire(key, self.window_seconds)
            return current <= self.max_requests
        # Fallback en memoria
        now = time.time()
        self.fallback_clients[client_ip] = [
            ts for ts in self.fallback_clients[client_ip]
            if now - ts < self.window_seconds
        ]
        if len(self.fallback_clients[client_ip]) >= self.max_requests:
            return False
        self.fallback_clients[client_ip].append(now)
        return True

rate_limiter = DistributedRateLimiter(max_requests=30, window_seconds=60)

# --- API Key Auth (DevSecOps: autenticación configurable) ---
OPTIBUS_API_KEY = os.getenv("OPTIBUS_API_KEY", "").strip()
API_KEY_ENABLED = len(OPTIBUS_API_KEY) >= 16

if API_KEY_ENABLED:
    logger.info("API Key auth HABILITADA para endpoints GPS")
else:
    logger.warning("API Key auth DESHABILITADA. Define OPTIBUS_API_KEY (mín. 16 chars) para activar.")

security = HTTPBearer(auto_error=False)

async def verify_api_key(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    if not API_KEY_ENABLED:
        return True
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key requerida. Usa Authorization: Bearer <key>",
        )
    if not compare_digest(credentials.credentials, OPTIBUS_API_KEY):
        logger.warning(f"Intento de acceso con API Key inválida: {credentials.credentials[:4]}...")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="API Key inválida",
        )
    return True

# Manejador de conexiones WebSocket con logging
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        logger.info(f"WebSocket conectado. Conexiones activas: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)
        logger.info(f"WebSocket desconectado. Conexiones activas: {len(self.active_connections)}")

    async def broadcast(self, message: str):
        disconnected = []
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except Exception as e:
                logger.warning(f"Error enviando broadcast a WS: {e}")
                disconnected.append(connection)
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

manager = ConnectionManager()

# --- Background task para simular buses (multi-ruta) ---
async def bus_simulator():
    await asyncio.sleep(5)
    
    async with engine.begin() as conn:
        result = await conn.execute(
            select(models.Route.id, func.ST_AsGeoJSON(models.Route.geom))
        )
        routes_data = result.all()
    
    if not routes_data:
        logger.warning("No hay rutas para simular.")
        return
    
    all_buses = []
    for route_id, geojson_str in routes_data:
        geojson = json.loads(geojson_str)
        coords = geojson.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue
        all_buses.append({
            "id": f"bus_r{route_id}_1",
            "idx": 0,
            "direction": 1,
            "coords": coords,
            "route_id": route_id
        })
        if len(coords) > 4:
            all_buses.append({
                "id": f"bus_r{route_id}_2",
                "idx": len(coords) // 2,
                "direction": 1,
                "coords": coords,
                "route_id": route_id
            })
    
    if not all_buses:
        logger.warning("No hay coordenadas válidas para simular.")
        return
    
    logger.info(f"Simulador iniciado con {len(all_buses)} buses en {len(routes_data)} rutas.")
    
    while True:
        if manager.active_connections:
            buses_payload = []
            for bus in all_buses:
                lon, lat = bus["coords"][bus["idx"]]
                buses_payload.append({"id": bus["id"], "lat": lat, "lon": lon})
                
                bus["idx"] += bus["direction"]
                if bus["idx"] >= len(bus["coords"]) or bus["idx"] < 0:
                    bus["direction"] *= -1
                    bus["idx"] += bus["direction"] * 2
                bus["idx"] = bus["idx"] % len(bus["coords"])
            
            await manager.broadcast(json.dumps({"type": "bus_positions", "buses": buses_payload}))
        await asyncio.sleep(3)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    task = None
    if os.getenv("ENABLE_BUS_SIMULATOR", "false").lower() == "true":
        task = asyncio.create_task(bus_simulator())
        logger.info("Simulador de buses HABILITADO (multi-ruta).")
    
    yield
    if task:
        task.cancel()

app = FastAPI(title="OptiBus", version="0.4.0", lifespan=lifespan)

# Métricas Prometheus
instrumentator = Instrumentator().instrument(app)
instrumentator.expose(app, include_in_schema=False)

# CORS
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:80,http://localhost,http://127.0.0.1").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Rate limiting
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    if not await rate_limiter.is_allowed(client_ip):
        logger.warning(f"Rate limit excedido para IP: {client_ip}")
        return JSONResponse(status_code=429, content={"detail": "Demasiadas solicitudes."})
    return await call_next(request)

# --- Endpoints ---

@app.get("/health")
async def health_check():
    db_status = "unknown"
    redis_status = "unknown"
    try:
        async with engine.begin() as conn:
            await conn.execute(select(func.literal(1)))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {type(e).__name__}"
    try:
        r = await get_redis()
        if r:
            await r.ping()
            redis_status = "connected"
        else:
            redis_status = "disabled"
    except Exception as e:
        redis_status = f"error: {type(e).__name__}"
    return {"status": "ok", "service": "optibus-api", "version": "0.4.0", "database": db_status, "redis": redis_status}

@app.get("/api/routes")
async def get_routes(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(models.Route.id, models.Route.name, func.ST_AsGeoJSON(models.Route.geom).label('geojson'))
    )
    features = []
    for row in result:
        features.append({
            "type": "Feature",
            "properties": {"id": row.id, "name": row.name},
            "geometry": json.loads(row.geojson)
        })
    return {"type": "FeatureCollection", "features": features}

@app.get("/api/stops/nearby")
async def get_nearby_stops(
    lat: float, lon: float, radius_meters: float = 500.0, max_results: int = Query(default=50, le=200),
    db: AsyncSession = Depends(get_db)
):
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return JSONResponse(status_code=400, content={"detail": "Coordenadas inválidas."})
    if radius_meters > 10000:
        return JSONResponse(status_code=400, content={"detail": "Radio máximo: 10000 metros."})
    
    point = f"SRID=4326;POINT({lon} {lat})"
    query = select(
        models.Stop.id, models.Stop.name,
        func.ST_AsGeoJSON(models.Stop.geom).label('geojson'),
        func.ST_DistanceSphere(models.Stop.geom, func.ST_GeomFromText(point, 4326)).label('distance')
    ).where(
        func.ST_DWithin(cast(models.Stop.geom, Geography), cast(func.ST_GeomFromText(point, 4326), Geography), radius_meters)
    ).order_by('distance').limit(max_results)
    
    result = await db.execute(query)
    stops = [{"id": r.id, "name": r.name, "distance": round(r.distance, 2), "geometry": json.loads(r.geojson)} for r in result]
    return {"radius_meters": radius_meters, "nearby_stops": stops}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            text = await asyncio.wait_for(websocket.receive_text(), timeout=120.0)
            try:
                data = json.loads(text)
                if data.get("type") == "bus_positions":
                    for bus in data.get("buses", []):
                        bus["source"] = "real"
                    await manager.broadcast(json.dumps(data))
            except json.JSONDecodeError:
                logger.warning(f"JSON inválido en WS: {text}")
    except asyncio.TimeoutError:
        logger.info("WebSocket timeout")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
    finally:
        manager.disconnect(websocket)

# --- GPS Payload ---
class GPSPayload(BaseModel):
    bus_id: str
    lat: float
    lon: float
    speed: float = 0.0
    route_id: int | None = None

    @field_validator('lat')
    @classmethod
    def validate_lat(cls, v): 
        if not -90 <= v <= 90: raise ValueError('Latitud inválida')
        return v
    @field_validator('lon')
    @classmethod
    def validate_lon(cls, v): 
        if not -180 <= v <= 180: raise ValueError('Longitud inválida')
        return v

@app.post("/api/gps/update")
async def receive_gps(payload: GPSPayload, request: Request, _auth: None = Depends(verify_api_key), db: AsyncSession = Depends(get_db)):
    """Recibe posición GPS y la guarda en historial + broadcast."""
    
    # Guardar en historial
    point = f"SRID=4326;POINT({payload.lon} {payload.lat})"
    try:
        db.add(models.BusPosition(
            bus_id=payload.bus_id,
            geom=func.ST_GeomFromText(point, 4326),
            speed=payload.speed,
            route_id=payload.route_id,
            recorded_at=datetime.now(timezone.utc)
        ))
        await db.commit()
    except Exception as e:
        logger.error(f"Error guardando posición: {e}")
        await db.rollback()
    
    # Broadcast WebSocket
    await manager.broadcast(json.dumps({
        "type": "bus_positions",
        "buses": [{"id": payload.bus_id, "lat": payload.lat, "lon": payload.lon, "source": "real", "route_id": payload.route_id}]
    }))
    return {"status": "success"}

@app.post("/api/gps/owntracks")
async def receive_owntracks(payload: dict, request: Request, _auth: None = Depends(verify_api_key)):
    if payload.get("_type") == "location":
        lat, lon = payload.get("lat"), payload.get("lon")
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)): return {"status": "error"}
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180): return {"status": "error"}
        tracker_id = payload.get("tid", "BUS")
        await manager.broadcast(json.dumps({
            "type": "bus_positions",
            "buses": [{"id": f"BUS-{tracker_id.upper()}", "lat": lat, "lon": lon, "source": "owntracks_native"}]
        }))
        return {"status": "success"}
    return {"status": "ignored"}

# --- Historial de posiciones ---
@app.get("/api/bus/history")
async def get_bus_history(
    _auth: None = Depends(verify_api_key),
    bus_id: str = Query(..., min_length=1),
    minutes: int = Query(default=30, le=1440),
    db: AsyncSession = Depends(get_db)
):
    """Obtiene el historial de posiciones de un bus en los últimos N minutos."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    result = await db.execute(
        select(
            models.BusPosition.bus_id,
            func.ST_Y(models.BusPosition.geom).label('lat'),
            func.ST_X(models.BusPosition.geom).label('lon'),
            models.BusPosition.speed,
            models.BusPosition.recorded_at
        ).where(
            and_(models.BusPosition.bus_id == bus_id, models.BusPosition.recorded_at >= since)
        ).order_by(models.BusPosition.recorded_at.asc()).limit(2000)
    )
    positions = [{"lat": r.lat, "lon": r.lon, "speed": r.speed, "time": r.recorded_at.isoformat()} for r in result]
    return {"bus_id": bus_id, "minutes": minutes, "count": len(positions), "positions": positions}

@app.get("/api/bus/active")
async def get_active_buses(_auth: None = Depends(verify_api_key), minutes: int = Query(default=5, le=60), db: AsyncSession = Depends(get_db)):
    """Lista buses activos en los últimos N minutos."""
    since = datetime.now(timezone.utc) - timedelta(minutes=minutes)
    subq = select(
        models.BusPosition.bus_id,
        func.max(models.BusPosition.recorded_at).label('last_seen')
    ).where(models.BusPosition.recorded_at >= since).group_by(models.BusPosition.bus_id).subquery()
    
    result = await db.execute(
        select(
            models.BusPosition.bus_id,
            func.ST_Y(models.BusPosition.geom).label('lat'),
            func.ST_X(models.BusPosition.geom).label('lon'),
            models.BusPosition.speed,
            subq.c.last_seen
        ).join(subq, and_(
            models.BusPosition.bus_id == subq.c.bus_id,
            models.BusPosition.recorded_at == subq.c.last_seen
        )).order_by(models.BusPosition.bus_id)
    )
    buses = [{"bus_id": r.bus_id, "lat": r.lat, "lon": r.lon, "speed": round(r.speed, 1), "last_seen": r.last_seen.isoformat()} for r in result]
    return {"active_count": len(buses), "buses": buses}

# --- Dashboard Admin (HTML) ---
@app.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(_auth: None = Depends(verify_api_key)):
    return HTMLResponse("""
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OptiBus Admin Dashboard</title>
    <style>
        *{margin:0;padding:0;box-sizing:border-box}
        body{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:20px}
        h1{text-align:center;margin-bottom:20px;color:#38bdf8}
        .grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;max-width:1200px;margin:0 auto}
        .card{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}
        .card h2{font-size:1rem;color:#94a3b8;margin-bottom:8px}
        .card .value{font-size:2rem;font-weight:bold;color:#38bdf8}
        .card .sub{font-size:.8rem;color:#64748b;margin-top:4px}
        table{width:100%;border-collapse:collapse;margin-top:12px}
        th,td{padding:8px 12px;text-align:left;border-bottom:1px solid #334155}
        th{color:#94a3b8;font-weight:600;font-size:.8rem}
        td{font-size:.9rem}
        .badge{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75rem}
        .badge-active{background:#065f46;color:#6ee7b7}
        .status-bar{display:flex;gap:16px;justify-content:center;margin-bottom:20px;flex-wrap:wrap}
        .status-dot{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}
        .status-dot.ok{background:#10b981}
        .status-dot.err{background:#ef4444}
        #alert-box{background:#7f1d1d;border:1px solid #ef4444;padding:12px;border-radius:8px;margin-top:16px;display:none}
        .route-badge{background:#1e40af;color:#93c5fd;padding:2px 8px;border-radius:6px;font-size:.75rem}
    </style>
</head>
<body>
    <h1>🚌 OptiBus Admin Dashboard</h1>
    <div class="status-bar" id="statusBar"></div>
    <div class="grid">
        <div class="card"><h2>🚌 Buses Activos</h2><div class="value" id="activeBuses">-</div><div class="sub">Últimos 5 minutos</div></div>
        <div class="card"><h2>🔌 WebSocket</h2><div class="value" id="wsClients">-</div><div class="sub">Conexiones activas</div></div>
        <div class="card"><h2>📡 Posiciones (24h)</h2><div class="value" id="totalPositions">-</div><div class="sub">Registros GPS guardados</div></div>
        <div class="card"><h2>🛡️ API Key</h2><div class="value" id="apiKeyStatus">-</div><div class="sub">Estado de autenticación</div></div>
    </div>
    <div class="card" style="max-width:1200px;margin:16px auto">
        <h2>📍 Buses Activos Ahora</h2>
        <div style="overflow-x:auto"><table><thead><tr><th>Bus ID</th><th>Latitud</th><th>Longitud</th><th>Velocidad</th><th>Última vez</th></tr></thead><tbody id="busesTable"></tbody></table></div>
    </div>
    <div id="alert-box">⚠️ <span id="alertMessage"></span></div>
    <script>
        async function loadData(){
            try{
                const h=await fetch('/health');const hd=await h.json();
                document.getElementById('statusBar').innerHTML=
                    `<span><span class="status-dot ${hd.database==='connected'?'ok':'err'}"></span>DB: ${hd.database}</span>`+
                    `<span><span class="status-dot ${hd.redis==='connected'?'ok':'err'}"></span>Redis: ${hd.redis}</span>`+
                    `<span>v${hd.version}</span>`;
                
                const ab=await fetch('/api/bus/active?minutes=5');const abd=await ab.json();
                document.getElementById('activeBuses').textContent=abd.active_count;
                const tb=document.getElementById('busesTable');
                tb.innerHTML=abd.buses.map(b=>
                    `<tr><td>${b.bus_id}</td><td>${b.lat.toFixed(6)}</td><td>${b.lon.toFixed(6)}</td><td>${b.speed} km/h</td><td>${new Date(b.last_seen).toLocaleTimeString()}</td></tr>`
                ).join('')||'<tr><td colspan="5">No hay buses activos</td></tr>';
                
                const ak=await fetch('/api/auth/status');const akd=await ak.json();
                document.getElementById('apiKeyStatus').textContent=akd.api_key_enabled?'🔒 Habilitada':'⚠️ Deshabilitada';
            }catch(e){console.error(e)}
        }
        loadData();setInterval(loadData,10000);
    </script>
</body>
</html>""")

# --- Endpoint estado de API Key (admin) ---
@app.get("/api/auth/status")
async def auth_status(_auth: None = Depends(verify_api_key)):
    return {"api_key_enabled": API_KEY_ENABLED, "version": "0.4.0"}

# --- Geocerca / Alerta de desvío ---
@app.get("/api/alert/geofence")
async def check_geofence(
    _auth: None = Depends(verify_api_key),
    bus_id: str = Query(...),
    lat: float = Query(...),
    lon: float = Query(...),
    max_distance_meters: float = Query(default=200.0, le=5000.0),
    db: AsyncSession = Depends(get_db)
):
    """Verifica si un bus está dentro de la geocerca de alguna ruta."""
    point = f"SRID=4326;POINT({lon} {lat})"
    result = await db.execute(
        select(
            models.Route.id, models.Route.name,
            func.ST_Distance(models.Route.geom, func.ST_GeomFromText(point, 4326)).label('distance')
        ).where(
            func.ST_DWithin(models.Route.geom, func.ST_GeomFromText(point, 4326), max_distance_meters)
        ).order_by('distance').limit(1)
    )
    row = result.first()
    if row:
        return {"bus_id": bus_id, "status": "on_route", "route_name": row.name, "route_id": row.id, "distance_m": round(row.distance, 1)}
    return {"bus_id": bus_id, "status": "off_route", "alert": f"Bus fuera de ruta (>{max_distance_meters}m)"}

# --- ETA: tiempo estimado a una parada ---
@app.get("/api/eta")
async def estimate_eta(
    _auth: None = Depends(verify_api_key),
    bus_id: str = Query(...),
    stop_id: int = Query(...),
    db: AsyncSession = Depends(get_db)
):
    """Estima tiempo de llegada a una parada basado en la última posición y velocidad."""
    # Última posición del bus
    last_pos = await db.execute(
        select(
            func.ST_Y(models.BusPosition.geom).label('lat'),
            func.ST_X(models.BusPosition.geom).label('lon'),
            models.BusPosition.speed,
            models.BusPosition.recorded_at
        ).where(models.BusPosition.bus_id == bus_id)
        .order_by(desc(models.BusPosition.recorded_at)).limit(1)
    )
    pos = last_pos.first()
    if not pos:
        return JSONResponse(status_code=404, content={"detail": "Bus sin datos recientes"})
    
    # Posición de la parada
    stop = await db.execute(
        select(func.ST_Y(models.Stop.geom).label('lat'), func.ST_X(models.Stop.geom).label('lon'), models.Stop.name)
        .where(models.Stop.id == stop_id)
    )
    stop_row = stop.first()
    if not stop_row:
        return JSONResponse(status_code=404, content={"detail": "Parada no encontrada"})
    
    # Distancia (haversine simplificada)
    R = 6371000
    dlat = math.radians(stop_row.lat - pos.lat)
    dlon = math.radians(stop_row.lon - pos.lon)
    a = math.sin(dlat/2)**2 + math.cos(math.radians(pos.lat)) * math.cos(math.radians(stop_row.lat)) * math.sin(dlon/2)**2
    distance_m = R * 2 * math.atan2(math.sqrt(a), math.sqrt(1-a))
    
    speed_ms = max(pos.speed / 3.6, 2.78) if pos.speed > 0 else 8.33  # min 10 km/h, default 30 km/h
    eta_seconds = distance_m / speed_ms
    eta_minutes = round(eta_seconds / 60, 1)
    
    time_diff = (datetime.now(timezone.utc) - pos.recorded_at).total_seconds() if pos.recorded_at else 0
    
    return {
        "bus_id": bus_id,
        "stop_id": stop_id,
        "stop_name": stop_row.name,
        "distance_m": round(distance_m, 1),
        "eta_minutes": eta_minutes,
        "speed_kmh": round(speed_ms * 3.6, 1),
        "last_position_age_seconds": round(time_diff, 1)
    }

# --- Configuración del simulador ---
# --- Directorio para rutas grabadas ---
RECORDED_ROUTES_DIR = Path(__file__).parent / "data" / "recorded_routes"
RECORDED_ROUTES_DIR.mkdir(parents=True, exist_ok=True, mode=0o755)

@app.post("/api/routes/upload")
async def upload_recorded_route(
    _auth: None = Depends(verify_api_key),
    gpx_file: UploadFile = File(...),
    stops_json: str = Form(...),
    company: str = Form(default=""),
    route_name: str = Form(...),
    tags: str = Form(default=""),
    db: AsyncSession = Depends(get_db)
):
    """
    Recibe una ruta grabada desde el APK.
    - Ingiere la ruta GPX directamente en PostGIS
    - Guarda las paradas en la BD asociadas a la ruta
    - Guarda copia JSON/GPX en backend/data/recorded_routes/ para auditoría
    """
    # Validar nombre de ruta
    safe_route_name = re.sub(r'[^a-zA-Z0-9áéíóúÁÉÍÓÚñÑüÜ _\-]', '', route_name).strip()
    if not safe_route_name:
        raise HTTPException(status_code=400, detail="Nombre de ruta inválido")
    
    # Leer y parsear GPX
    try:
        gpx_content = await gpx_file.read()
        gpx = gpxpy.parse(gpx_content.decode("utf-8"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Error parseando GPX: {e}")
    
    # Extraer puntos como (lat, lon, iso_time) para limpieza
    raw_points = []
    for track in gpx.tracks:
        for segment in track.segments:
            for point in segment.points:
                iso_time = point.time.isoformat() + "Z" if point.time else ""
                raw_points.append((point.latitude, point.longitude, iso_time))
    
    if len(raw_points) < 2:
        raise HTTPException(status_code=400, detail="Se requieren al menos 2 puntos GPS")
    
    # Limpiar y filtrar outliers usando gps_cleaner
    cleaned_points = clean_gps_track(raw_points)
    removed = len(raw_points) - len(cleaned_points)
    if removed > 0:
        logger.info(f"GPS cleaner eliminó {removed} de {len(raw_points)} puntos (outliers/ruido)")
    
    if len(cleaned_points) < 2:
        raise HTTPException(
            status_code=400,
            detail=f"Después de limpiar solo quedaron {len(cleaned_points)} puntos. La ruta tiene demasiado ruido GPS."
        )
    
    # Convertir puntos limpios a WKT LINESTRING
    wkt_coords = [f"{lon} {lat}" for lat, lon, _ in cleaned_points]
    linestring_wkt = f"SRID=4326;LINESTRING({', '.join(wkt_coords)})"
    new_route = models.Route(name=safe_route_name, geom=linestring_wkt)
    db.add(new_route)
    await db.flush()  # Obtener el ID generado
    
    # Parsear y guardar paradas
    stops_count = 0
    try:
        stops_data = json.loads(stops_json)
        if isinstance(stops_data, list):
            for stop in stops_data:
                if isinstance(stop, dict) and "lat" in stop and "lon" in stop:
                    stop_name = stop.get("name", f"Parada {stops_count+1}")
                    stop_point = f"SRID=4326;POINT({stop['lon']} {stop['lat']})"
                    db.add(models.Stop(
                        name=str(stop_name)[:255],
                        route_id=new_route.id,
                        geom=stop_point
                    ))
                    stops_count += 1
    except json.JSONDecodeError:
        logger.warning("stops_json no es JSON válido, guardando ruta sin paradas")
    
    await db.commit()
    
    # Guardar copia de auditoría en backend/data/recorded_routes/
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_filename = f"{safe_route_name.replace(' ', '_')}_{timestamp}"
    
    # Guardar GPX original
    gpx_path = RECORDED_ROUTES_DIR / f"{base_filename}.gpx"
    async with aiofiles.open(gpx_path, "wb") as f:
        await f.write(gpx_content)
    
    total_points = len(cleaned_points)
    
    # Guardar metadatos JSON
    meta_path = RECORDED_ROUTES_DIR / f"{base_filename}_meta.json"
    meta = {
        "route_name": safe_route_name,
        "company": company,
        "tags": [t.strip() for t in tags.split(",") if t.strip()],
        "points_raw": len(raw_points),
        "points_clean": total_points,
        "outliers_removed": removed,
        "stops_count": stops_count,
        "recorded_at": datetime.now(timezone.utc).isoformat(),
        "route_id": new_route.id
    }
    async with aiofiles.open(meta_path, "w") as f:
        await f.write(json.dumps(meta, indent=2, ensure_ascii=False))
    
    logger.info(f"Ruta '{safe_route_name}' subida: {total_points} puntos limpios, {stops_count} paradas (ID: {new_route.id}) - {removed} outliers eliminados")
    
    return {
        "status": "success",
        "route_id": new_route.id,
        "route_name": safe_route_name,
        "points_cleaned": total_points,
        "outliers_removed": removed,
        "stops": stops_count,
        "saved_files": [
            str(gpx_path.relative_to(Path(__file__).parent)),
            str(meta_path.relative_to(Path(__file__).parent))
        ]
    }

@app.get("/api/simulator/status")
async def simulator_status(_auth: None = Depends(verify_api_key)):
    return {"simulator_enabled": os.getenv("ENABLE_BUS_SIMULATOR", "false").lower() == "true", "active_ws_connections": len(manager.active_connections)}