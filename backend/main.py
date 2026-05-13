from fastapi import FastAPI, Depends, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
from database import engine, Base, get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, cast
from geoalchemy2.types import Geography
import models
import asyncio
import json

# Manejador de conexiones WebSocket
class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections:
            try:
                await connection.send_text(message)
            except:
                pass

manager = ConnectionManager()

# Background task para simular buses
async def bus_simulator():
    """Simula el movimiento de buses siguiendo las rutas de PostGIS."""
    # Retraso inicial para dejar que la BD y app levanten bien
    await asyncio.sleep(5)
    
    # Extraer las coordenadas de la ruta 1 para simulación
    async with engine.begin() as conn:
        # Obtenemos la ruta en formato GeoJSON para procesarla
        result = await conn.execute(
            select(func.ST_AsGeoJSON(models.Route.geom)).where(models.Route.id == 1)
        )
        row = result.scalar()
        
    if not row:
        print("No hay rutas para simular.")
        return
        
    geojson = json.loads(row)
    # geojson['coordinates'] es una lista de [lon, lat]
    coordinates = geojson.get("coordinates", [])
    
    # Simularemos 2 buses en posiciones distintas de la lista
    bus1_idx = 0
    bus2_idx = len(coordinates) // 2
    
    while True:
        if manager.active_connections:
            # Bus 1
            lon1, lat1 = coordinates[bus1_idx]
            # Bus 2
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
            
        await asyncio.sleep(3) # Emitir cada 3 segundos

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Al iniciar la aplicación, creamos las tablas en la BD (incluyendo columnas espaciales)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Lanzar la tarea de simulación en segundo plano
    task = asyncio.create_task(bus_simulator())
    yield
    task.cancel()

app = FastAPI(title="OptiBus MVP", version="0.1.0", lifespan=lifespan)

# Configurar CORS para que el PWA (Frontend) pueda comunicarse
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "optibus-api"}

@app.get("/api/routes")
async def get_routes(db: AsyncSession = Depends(get_db)):
    """Devuelve las rutas almacenadas en formato GeoJSON FeatureCollection para Leaflet."""
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
async def get_nearby_stops(lat: float, lon: float, radius_meters: float = 500.0, db: AsyncSession = Depends(get_db)):
    """Encuentra paradas cercanas a una coordenada usando ST_DWithin."""
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
    """Endpoint WebSocket para que el frontend reciba posiciones en tiempo real."""
    await manager.connect(websocket)
    try:
        while True:
            # Mantener la conexión abierta escuchando posibles pings
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)