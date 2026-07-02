"""
OptiBus Bus Simulator — DevSecOps v5.0
Simulador de buses multi-ruta para desarrollo/testing.
Persiste posiciones en PostgreSQL para que /api/bus/active funcione.
"""

import asyncio
import json
import logging
from datetime import UTC, datetime

import models
from database import SessionLocal, engine
from sqlalchemy import func, select, text as sa_text
from ws_manager import ConnectionManager

logger = logging.getLogger("optibus-simulator")

_simulator_task: asyncio.Task | None = None
_simulator_running = False


async def bus_simulator(ws_manager: ConnectionManager):
    """Simulador de buses en segundo plano (multi-ruta) con persistencia en DB."""
    global _simulator_running
    _simulator_running = True

    await asyncio.sleep(5)

    async with engine.begin() as conn:
        result = await conn.execute(
            select(models.Route.id, func.ST_AsGeoJSON(models.Route.geom))
        )
        routes_data = result.all()

    if not routes_data:
        logger.warning("No hay rutas para simular.")
        _simulator_running = False
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
            "route_id": route_id,
        })
        if len(coords) > 4:
            all_buses.append({
                "id": f"bus_r{route_id}_2",
                "idx": len(coords) // 2,
                "direction": 1,
                "coords": coords,
                "route_id": route_id,
            })

    if not all_buses:
        logger.warning("No hay coordenadas validas para simular.")
        _simulator_running = False
        return

    logger.info(
        f"Simulador iniciado con {len(all_buses)} buses en {len(routes_data)} rutas."
    )

    while _simulator_running:
        if ws_manager.active_count > 0:
            buses_payload = []
            for bus in all_buses:
                lon, lat = bus["coords"][bus["idx"]]
                buses_payload.append({
                    "id": bus["id"],
                    "lat": lat,
                    "lon": lon,
                    "source": "simulated",
                    "route_id": bus["route_id"],
                })
                bus["idx"] += bus["direction"]
                if bus["idx"] >= len(bus["coords"]) or bus["idx"] < 0:
                    bus["direction"] *= -1
                    bus["idx"] += bus["direction"] * 2
                bus["idx"] = bus["idx"] % len(bus["coords"])

            await ws_manager.broadcast(json.dumps({
                "type": "bus_positions",
                "buses": buses_payload,
            }))

            # Persistir en DB
            try:
                async with SessionLocal() as db:
                    for entry in buses_payload:
                        point = f"SRID=4326;POINT({entry['lon']} {entry['lat']})"
                        db.add(models.BusPosition(
                            cooperative_id=1,
                            bus_id=entry["id"],
                            geom=sa_text(f"ST_GeomFromText('{point}', 4326)"),
                            speed=25.0,
                            route_id=entry.get("route_id"),
                            recorded_at=datetime.now(UTC),
                        ))
                    await db.commit()
            except Exception:
                pass

        await asyncio.sleep(3)

    logger.info("Simulador de buses detenido")


async def start_simulator(ws_manager: ConnectionManager):
    import os
    global _simulator_task, _simulator_running
    if _simulator_running:
        return
    if os.getenv("ENABLE_BUS_SIMULATOR", "false").lower() == "true":
        logger.info("Simulador de buses HABILITADO (multi-ruta).")
        _simulator_task = asyncio.create_task(bus_simulator(ws_manager))


async def stop_simulator():
    global _simulator_task, _simulator_running
    _simulator_running = False
    if _simulator_task:
        _simulator_task.cancel()
        try:
            await _simulator_task
        except asyncio.CancelledError:
            pass
        _simulator_task = None