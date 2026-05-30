from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect, Request, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, field_validator
from contextlib import asynccontextmanager
from database import engine, Base, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast
from geoalchemy2.types import Geography
import models
import asyncio
import json
import logging
import os
import time
from collections import defaultdict
from secrets import compare_digest

# --- Logging estructurado ---
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s'
)
logger = logging.getLogger("optibus-api")

# --- API Key Auth (DevSecOps: autenticación configurable) ---
# Si OPTIBUS_API_KEY no está definida, la autenticación se desactiva
# (retrocompatible con despliegues existentes). Si se define, los endpoints
# de escritura GPS requieren el header Authorization: Bearer <key>
OPTIBUS_API_KEY = os.getenv("OPTIBUS_API_KEY", "").strip()
API_KEY_ENABLED = len(OPTIBUS_API_KEY) >= 16  # mínimo 16 chars para considerarse válida

if API_KEY_ENABLED:
    logger.info("API Key auth HABILITADA para endpoints GPS")
else:
    logger.warning("API Key auth DESHABILITADA. Define OPTIBUS_API_KEY (mín. 16 chars) para activar.")

security = HTTPBearer(auto_error=False)

async def verify_api_key(credentials: HTTPAuthorizationCredentials | None = Depends(security)):
    """Valida API Key solo si está configurada. Si no hay key, deja pasar (retrocompatibilidad)."""
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

# --- Rate Limiter simple (DevSecOps: anti-abuso) ---
class RateLimiter:
    def __init__(self, max_requests: int = 30, window_seconds: int = 60):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.clients: dict[str, list[float]] = defaultdict(list)

    def is_allowed(self, client_ip: str) -> bool:
        now = time.time()
        # Limpiar timestamps antiguos
        self.clients[client_ip] = [
            ts for ts in self.clients[client_ip]
            if now - ts < self.window_seconds
        ]
        if len(self.clients[client_ip]) >= self.max_requests:
            return False
        self.clients[client_ip].append(now)
        return True

rate_limiter = RateLimiter(max_requests=30, window_seconds=60)

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
        # Limpiar conexiones fallidas
        for conn in disconnected:
            if conn in self.active_connections:
                self.active_connections.remove(conn)

manager = ConnectionManager()

# --- Background task para simular buses ---
async def bus_simulator():
    """Simula el movimiento de buses siguiendo las rutas de PostGIS."""
    await asyncio.sleep(5)
    
    async with engine.begin() as conn:
        result = await conn.execute(
            select(func.ST_AsGeoJSON(models.Route.geom)).where(models.Route.id == 1)
        )
        row = result.scalar()
        
    if not row:
        logger.warning("No hay rutas para simular.")
        return
        
    geojson = json.loads(row)
    coordinates = geojson.get("coordinates", [])
    
    if not coordinates:
        logger.warning("Ruta vacía, no se puede simular.")
        return
    
    bus1_idx = 0
    bus2_idx = len(coordinates) // 2
    
    logger.info(f"Simulador iniciado con {len(coordinates)} puntos de ruta.")
    
    while True:
        if manager.active_connections:
            lon1, lat1 = coordinates[bus1_idx]
            lon2, lat2 = coordinates[bus2_idx]
            
            payload = json.dumps({
                "type": "bus_positions",
                "buses": [
                    {"id": "bus_1", "lat": lat1, "lon": lon1},
                    {"id": "bus_2", "lat": lat2, "lon": lon2}
                ]
            })
            
            await manager.broadcast(payload)
            
            bus1_idx = (bus1_idx + 1) % len(coordinates)
            bus2_idx = (bus2_idx + 1) % len(coordinates)
            
        await asyncio.sleep(3)

@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    task = None
    if os.getenv("ENABLE_BUS_SIMULATOR", "false").lower() == "true":
        task = asyncio.create_task(bus_simulator())
        logger.info("Simulador de buses HABILITADO.")
    else:
        logger.info("Simulador de buses DESHABILITADO (variable ENABLE_BUS_SIMULATOR=false).")
    
    yield
    if task:
        task.cancel()

app = FastAPI(title="OptiBus MVP", version="0.2.0", lifespan=lifespan)

# DevSecOps: CORS restrictivo (no usar "*" en producción)
ALLOWED_ORIGINS = os.getenv("CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],  # Solo métodos necesarios
    allow_headers=["*"],
)

# --- Middleware de Rate Limiting ---
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    client_ip = request.client.host if request.client else "unknown"
    if not rate_limiter.is_allowed(client_ip):
        logger.warning(f"Rate limit excedido para IP: {client_ip}")
        return JSONResponse(
            status_code=429,
            content={"detail": "Demasiadas solicitudes. Intente de nuevo más tarde."}
        )
    response = await call_next(request)
    return response

@app.get("/health")
async def health_check():
    """Healthcheck que verifica también conectividad a la base de datos."""
    db_status = "unknown"
    try:
        async with engine.begin() as conn:
            await conn.execute(select(func.literal(1)))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {type(e).__name__}"
        logger.error(f"Healthcheck DB fallido: {e}")
    return {
        "status": "ok",
        "service": "optibus-api",
        "version": "0.3.0",
        "database": db_status
    }

@app.get("/api/routes")
async def get_routes(db: AsyncSession = Depends(get_db)):
    """Devuelve las rutas almacenadas en formato GeoJSON FeatureCollection para Leaflet."""
    logger.info("GET /api/routes solicitado")
    result = await db.execute(
        select(models.Route.id, models.Route.name, func.ST_AsGeoJSON(models.Route.geom).label('geojson'))
    )
    
    features = []
    for row in result:
        feature = {
            "type": "Feature",
            "properties": {
                "id": row.id,
                "name": row.name
            },
            "geometry": json.loads(row.geojson)
        }
        features.append(feature)
        
    return {
        "type": "FeatureCollection",
        "features": features
    }

@app.get("/api/stops/nearby")
async def get_nearby_stops(
    lat: float,
    lon: float,
    radius_meters: float = 500.0,
    db: AsyncSession = Depends(get_db)
):
    """Encuentra paradas cercanas a una coordenada usando ST_DWithin."""
    # DevSecOps: Validar rangos de coordenadas
    if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
        return JSONResponse(
            status_code=400,
            content={"detail": "Coordenadas inválidas. lat debe estar entre -90 y 90, lon entre -180 y 180."}
        )
    if radius_meters > 10000:
        return JSONResponse(
            status_code=400,
            content={"detail": "Radio máximo permitido: 10000 metros."}
        )
    
    logger.info(f"GET /api/stops/nearby lat={lat} lon={lon} radius={radius_meters}")
    
    point = f"SRID=4326;POINT({lon} {lat})"
    
    query = select(
        models.Stop.id,
        models.Stop.name,
        func.ST_AsGeoJSON(models.Stop.geom).label('geojson'),
        func.ST_DistanceSphere(
            models.Stop.geom, 
            func.ST_GeomFromText(point, 4326)
        ).label('distance') 
    ).where(
        func.ST_DWithin(
            cast(models.Stop.geom, Geography),
            cast(func.ST_GeomFromText(point, 4326), Geography),
            radius_meters
        )
    ).order_by('distance')
    
    result = await db.execute(query)
    
    stops = []
    for row in result:
        stops.append({
            "id": row.id,
            "name": row.name,
            "distance": round(row.distance, 2),
            "geometry": json.loads(row.geojson)
        })
        
    return {"radius_meters": radius_meters, "nearby_stops": stops}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """Endpoint WebSocket para que frontend y apps driver compartan posiciones en tiempo real."""
    await manager.connect(websocket)
    try:
        while True:
            # Esperar mensajes (posiciones del conductor) y hacer broadcast general
            text = await asyncio.wait_for(websocket.receive_text(), timeout=120.0)
            try:
                data = json.loads(text)
                # Si recibimos datos válidos de un bus, lo verificamos y reenviamos
                if data.get("type") == "bus_positions":
                    # Se inyecta "source":"real" para distinguir en Frontend
                    for bus in data.get("buses", []):
                        bus["source"] = "real"
                    await manager.broadcast(json.dumps(data))
            except json.JSONDecodeError:
                logger.warning(f"JSON inválido recibido en WS: {text}")
    except asyncio.TimeoutError:
        logger.info("WebSocket timeout (ping no recibido)")
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.error(f"WebSocket error inésperado: {e}")
    finally:
        manager.disconnect(websocket)

# --- FASE B: Endpoint de Recepción GPS (Móvil / IoT) ---

class GPSPayload(BaseModel):
    bus_id: str
    lat: float
    lon: float

    @field_validator('lat')
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not -90 <= v <= 90:
            raise ValueError('Latitud debe estar entre -90 y 90')
        return v

    @field_validator('lon')
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not -180 <= v <= 180:
            raise ValueError('Longitud debe estar entre -180 y 180')
        return v

@app.post("/api/gps/update")
async def receive_gps(payload: GPSPayload, request: Request, _auth: None = Depends(verify_api_key)):
    """Recibe la posición real de un bus/conductor y la retransmite al instante por WebSocket."""
    logger.info(f"GPS Update recibido de {payload.bus_id}: ({payload.lat}, {payload.lon}) desde {request.client.host}")
    
    ws_message = json.dumps({
        "type": "bus_positions",
        "buses": [
            {
                "id": payload.bus_id,
                "lat": payload.lat,
                "lon": payload.lon,
                "source": "real"
            }
        ]
    })
    
    await manager.broadcast(ws_message)
    
    return {"status": "success", "message": f"Posición de {payload.bus_id} retransmitida."}

# --- FASE B.2: Endpoint para App Nativa de Flotas FOSS (OwnTracks) ---
@app.post("/api/gps/owntracks")
async def receive_owntracks(payload: dict, request: Request, _auth: None = Depends(verify_api_key)):
    """
    Recibe un webhook nativo en segundo plano desde la aplicación libre 'OwnTracks'.
    """
    if payload.get("_type") == "location":
        lat = payload.get("lat")
        lon = payload.get("lon")
        
        # DevSecOps: Validar coordenadas recibidas
        if not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
            return {"status": "error", "reason": "Coordenadas inválidas"}
        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
            return {"status": "error", "reason": "Coordenadas fuera de rango"}
        
        tracker_id = payload.get("tid", "BUS")
        bus_id = f"BUS-{tracker_id.upper()}"
        
        logger.info(f"OwnTracks recibido de {bus_id}: ({lat}, {lon})")
        
        ws_message = json.dumps({
            "type": "bus_positions",
            "buses": [{
                "id": bus_id,
                "lat": lat,
                "lon": lon,
                "source": "owntracks_native"
            }]
        })
        
        await manager.broadcast(ws_message)
        return {"status": "success"}
    
    return {"status": "ignored", "reason": "Not a location payload"}
