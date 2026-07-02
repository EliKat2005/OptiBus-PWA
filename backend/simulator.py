"""
OptiBus Bus Simulator — DevSecOps v5.1
Simulador de buses multi-ruta con datos realistas para demo/pitch.
"""

import asyncio
import json
import logging
import random
from datetime import UTC, datetime

import models
from database import SessionLocal, engine
from sqlalchemy import func, select
from ws_manager import ConnectionManager

logger = logging.getLogger("optibus-simulator")

_simulator_task: asyncio.Task | None = None
_simulator_running = False

BUS_LABELS = ["ECO-001", "ECO-002", "ECO-003", "EXP-101", "EXP-102", "URB-201", "URB-202", "URB-203"]


async def bus_simulator(ws_manager: ConnectionManager):
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
    label_idx = 0
    for route_id, geojson_str in routes_data:
        geojson = json.loads(geojson_str)
        coords = geojson.get("coordinates", [])
        if not coords or len(coords) < 2:
            continue
        all_buses.append({
            "id": BUS_LABELS[label_idx % len(BUS_LABELS)],
            "idx": 0,
            "direction": 1,
            "coords": coords,
            "route_id": route_id,
        })
        label_idx += 1
        if len(coords) > 4 and label_idx < len(BUS_LABELS):
            all_buses.append({
                "id": BUS_LABELS[label_idx % len(BUS_LABELS)],
                "idx": len(coords) // 2,
                "direction": 1,
                "coords": coords,
                "route_id": route_id,
            })
            label_idx += 1

    if not all_buses:
        logger.warning("No hay coordenadas validas para simular.")
        _simulator_running = False
        return

    logger.info(f"Simulador iniciado con {len(all_buses)} buses realistas en {len(routes_data)} rutas.")

    iteration = 0
    while _simulator_running:
        iteration += 1
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

        # Persistir en DB con velocidades variables realistas (18-42 km/h para bus urbano)
        try:
            async with SessionLocal() as db:
                for entry in buses_payload:
                    point = f"SRID=4326;POINT({entry['lon']} {entry['lat']})"
                    db.add(models.BusPosition(
                        cooperative_id=1,
                        bus_id=entry["id"],
                        geom=func.ST_GeomFromText(point, 4326),
                        speed=round(random.uniform(18.0, 42.0), 1),
                        route_id=entry.get("route_id"),
                        recorded_at=datetime.now(UTC),
                    ))
                await db.commit()
        except Exception as e:
            logger.debug(f"Simulador DB: {e}")

        if ws_manager.active_count > 0:
            await ws_manager.broadcast(json.dumps({
                "type": "bus_positions",
                "buses": buses_payload,
            }))

        # Demo: infractiones cada 45s
        if iteration % 15 == 0 and all_buses:
            demo_bus = all_buses[iteration % len(all_buses)]
            lon_demo, lat_demo = demo_bus["coords"][demo_bus["idx"]]
            try:
                async with SessionLocal() as db:
                    db.add(models.Infraction(
                        cooperative_id=1, bus_id=demo_bus["id"], driver_id=1,
                        infraction_type="speeding", speed_kmh=round(random.uniform(65, 78), 1),
                        max_allowed_kmh=60.0, lat=lat_demo, lon=lon_demo,
                        recorded_at=datetime.now(UTC),
                    ))
                    await db.commit()
            except Exception:
                pass

        # Geo alerts cada 30s
        if iteration % 10 == 0 and all_buses:
            demo_bus = all_buses[iteration % len(all_buses)]
            try:
                async with SessionLocal() as db:
                    db.add(models.GeofenceAlert(
                        cooperative_id=1, bus_id=demo_bus["id"],
                        route_id=demo_bus.get("route_id"), alert_type="off_route",
                        message=f"Bus {demo_bus['id']} se desvio de la ruta asignada",
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