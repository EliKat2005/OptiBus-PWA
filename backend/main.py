"""
OptiBus API — DevSecOps v4.0
Main application factory con arquitectura modular.
Integra autenticación, rutas, GPS, WebSocket, rate limiting y monitoreo.
"""

import asyncio
import json
import logging
from contextlib import asynccontextmanager
from secrets import compare_digest

from admin import init_admin

# ── Importar módulos de rutas ──
from admin import router as admin_router
from auth_routes import router as auth_router
from auth_utils import (
    OPTIBUS_API_KEY,
    decode_jwt_token,
)
from config import (
    ALLOWED_ORIGINS,
    API_KEY_ENABLED,
    APP_VERSION,
    ensure_directories,
    validate_config,
)
from database import Base, engine
from fastapi import (
    FastAPI,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.middleware import SlowAPIMiddleware
from slowapi.errors import RateLimitExceeded
from b2b_routes import router as b2b_router
from b2g_routes import router as b2g_router
from gps_routes import init_gps_routes
from gps_routes import router as gps_router
from prometheus_fastapi_instrumentator import Instrumentator
from rate_limiter import DistributedRateLimiter, get_real_ip
from route_routes import init_route_routes
from route_routes import router as route_router
from simulator import start_simulator, stop_simulator
from sqlalchemy import text
from ws_manager import ConnectionManager

# ── Logging ──
# logging ya fue configurado por config.py con force=True
logger = logging.getLogger("optibus-api")

# ── Managers globales ──
ws_manager = ConnectionManager()
rate_limiter = DistributedRateLimiter()


# ── Lifespan ──
@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan: startup y shutdown de la aplicación."""
    # Startup — validar config y crear directorios PRIMERO
    validate_config()
    ensure_directories()
    logger.info(f"OptiBus API v{APP_VERSION} iniciando...")

    # Esperar a que la DB esté lista (reintentos)
    max_retries = 10
    for attempt in range(1, max_retries + 1):
        try:
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)
            logger.info("DB conectada y tablas listas")
            break
        except Exception as e:
            logger.warning(f"DB no disponible (intento {attempt}/{max_retries}): {type(e).__name__}")
            if attempt >= max_retries:
                logger.critical("No se pudo conectar a la DB después de varios intentos. La API arranca en modo degradado.")
                # NO hacer raise — dejar que la app viva y reporte error en /health
            await asyncio.sleep(3)

    await ws_manager.start()
    logger.info(f"OptiBus API v{APP_VERSION} iniciada")
    logger.info(
        f"API Key auth: {'🔒 HABILITADA' if API_KEY_ENABLED else '⚠️ DESHABILITADA'}"
    )

    # Inicializar módulos con el ws_manager
    init_gps_routes(ws_manager)
    init_route_routes(ws_manager)
    init_admin(ws_manager)

    # Iniciar simulador
    await start_simulator(ws_manager)

    yield

    # Shutdown
    await stop_simulator()
    await ws_manager.stop()
    logger.info("OptiBus API detenida")


# ── App Factory ──
app = FastAPI(
    title="OptiBus",
    version=APP_VERSION,
    lifespan=lifespan,
)

# ── Rate Limiting con slowapi ──
limiter = Limiter(key_func=get_remote_address, default_limits=["30/minute"])
app.state.limiter = limiter
app.add_middleware(SlowAPIMiddleware)
app.add_exception_handler(RateLimitExceeded, lambda request, exc: JSONResponse(
    status_code=429, content={"detail": f"Rate limit excedido: {exc.detail}"}
))

# ── Métricas Prometheus ──
instrumentator = Instrumentator().instrument(app)
instrumentator.expose(app, include_in_schema=False)

# ── CORS ──
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# ── Rate Limiting Middleware ──
@app.middleware("http")
async def rate_limit_middleware(request: Request, call_next):
    """Rate limiting con validación de X-Forwarded-For (DevSecOps)."""
    client_ip = (
        get_real_ip(
            request.client.host if request.client else "unknown",
            request.headers.get("X-Forwarded-For", ""),
        )
    )
    if not await rate_limiter.is_allowed(client_ip):
        logger.warning(f"Rate limit excedido para IP: {client_ip}")
        return JSONResponse(
            status_code=429, content={"detail": "Demasiadas solicitudes."}
        )
    return await call_next(request)


# ── Health Check ──
@app.get("/health")
async def health_check():
    """Endpoint de health check con status de DB y Redis."""
    db_status = "unknown"
    redis_status = "unknown"
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        db_status = "connected"
    except Exception as e:
        db_status = f"error: {type(e).__name__}"
    try:
        from rate_limiter import get_redis

        r = await get_redis()
        if r:
            await r.ping()
            redis_status = "connected"
        else:
            redis_status = "disabled"
    except Exception as e:
        redis_status = f"error: {type(e).__name__}"
    return {
        "status": "ok",
        "service": "optibus-api",
        "version": APP_VERSION,
        "database": db_status,
        "redis": redis_status,
    }


# ── WebSocket Endpoint ──
@app.websocket("/ws")
async def websocket_endpoint(
    websocket: WebSocket, token: str | None = Query(default=None)
):
    """
    WebSocket endpoint con rate limiting y autenticación opcional.
    DevSecOps: Autenticación vía JWT o API Key en query param.
    """
    client_id = ""

    # Autenticación opcional
    if API_KEY_ENABLED and token:
        if compare_digest(token, OPTIBUS_API_KEY):
            logger.info("WebSocket autenticado con API Key")
            client_id = "admin_ws"
        else:
            try:
                payload = decode_jwt_token(token)
                logger.info(
                    f"WebSocket autenticado con JWT: sub={payload.get('sub')}"
                )
                client_id = f"driver_{payload.get('sub')}"
            except Exception:
                logger.warning("WebSocket rechazado: token inválido")
                await websocket.close(code=4001, reason="Token inválido")
                return
    elif API_KEY_ENABLED and not token:
        logger.info("WebSocket conectado sin autenticación (público)")

    # Conectar
    client_id = await ws_manager.connect(websocket, client_id)

    try:
        while True:
            # Timeout para detectar clientes inactivos
            text = await asyncio.wait_for(websocket.receive_text(), timeout=120.0)

            # Rate limiting por cliente
            if await ws_manager.is_rate_limited(client_id):
                logger.warning(
                    f"WebSocket rate limit excedido: {client_id}"
                )
                await websocket.send_text(
                    json.dumps(
                        {
                            "type": "error",
                            "detail": "Rate limit excedido. Reduce la frecuencia de envío.",
                        }
                    )
                )
                continue

            try:
                data = json.loads(text)

                # Ignorar heartbeats/pings del cliente
                if data.get("type") == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
                    continue

                # Reenviar posiciones de buses (desde el APK)
                if data.get("type") == "bus_positions":
                    buses = data.get("buses", [])
                    if not isinstance(buses, list):
                        logger.warning(f"WS: buses no es lista de {client_id}")
                        continue
                    # Validar cada bus
                    validated_buses = []
                    for bus in buses:
                        if not isinstance(bus, dict):
                            continue
                        bid = bus.get("id")
                        lat = bus.get("lat")
                        lon = bus.get("lon")
                        if not isinstance(bid, str) or not isinstance(lat, (int, float)) or not isinstance(lon, (int, float)):
                            logger.warning(f"WS: bus inválido de {client_id}: {bus}")
                            continue
                        if not (-90 <= lat <= 90) or not (-180 <= lon <= 180):
                            continue
                        bus["source"] = bus.get("source", "real")
                        validated_buses.append(bus)
                    if validated_buses:
                        await ws_manager.broadcast(json.dumps({
                            "type": "bus_positions",
                            "buses": validated_buses
                        }))
                else:
                    # Mensaje desconocido, ignorar silenciosamente
                    logger.debug(f"Mensaje WS desconocido: {data.get('type')}")

            except json.JSONDecodeError:
                logger.warning(f"JSON inválido en WS de {client_id}")
    except TimeoutError:
        logger.info(f"WebSocket timeout: {client_id}")
    except WebSocketDisconnect:
        logger.debug(f"WebSocket disconnect: {client_id}")
    except Exception as e:
        logger.error(f"WebSocket error ({client_id}): {e}")
    finally:
        await ws_manager.disconnect(client_id)


# ── Registrar routers modulares ──
app.include_router(auth_router)
app.include_router(gps_router)
app.include_router(route_router)
app.include_router(admin_router)
app.include_router(b2b_router)
app.include_router(b2g_router)


# ── Bloque para métricas/admin Caddy ──
# Esto permite que Caddy redirija /metrics y /admin al backend.
# El propio Caddy restringe el acceso por IP interna.
@app.get("/metrics-info")
async def metrics_info():
    """Información sobre el endpoint de métricas."""
    return {
        "metrics_endpoint": "/metrics",
        "prometheus_enabled": True,
        "note": "El acceso a /metrics está restringido a IPs internas por Caddy.",
    }
