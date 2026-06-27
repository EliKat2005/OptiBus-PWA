#!/usr/bin/env python3
"""
OptiBus — Migración Multi-Tenant v1.0
=====================================
Crea una cooperativa por defecto y migra todos los datos existentes
sin cooperative_id para asignarlos a esa cooperativa.
Ejecutar UNA SOLA VEZ antes de desplegar el nuevo código.
"""

import asyncio
import hashlib
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../backend"))

from database import engine, Base
from models import Cooperative, Route, Stop, BusPosition, Driver
from sqlalchemy import select, text, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import sessionmaker

DEFAULT_COOPERATIVE_SLUG = "coop-28-septiembre"
DEFAULT_COOPERATIVE_NAME = "Cooperativa 28 de Septiembre"


async def migrate():
    session_factory = sessionmaker(engine, class_=AsyncSession)

    async with session_factory() as db:
        # ── 1. Crear tablas si no existen ──
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        # ── 2. Crear cooperativa default ──
        existing = await db.execute(
            select(Cooperative).where(Cooperative.slug == DEFAULT_COOPERATIVE_SLUG)
        )
        coop = existing.scalar_one_or_none()
        if coop:
            print(f"Cooperativa default ya existe: ID={coop.id}")
        else:
            api_key = os.getenv("OPTIBUS_API_KEY", "cooperative-default-key")
            coop = Cooperative(
                name=DEFAULT_COOPERATIVE_NAME,
                slug=DEFAULT_COOPERATIVE_SLUG,
                api_key_hash=hashlib.sha256(api_key.encode()).hexdigest(),
                max_buses=50,
                is_active=True,
            )
            db.add(coop)
            await db.flush()
            print(f"Cooperativa default creada: ID={coop.id}")

        coop_id = coop.id

        # ── 3. Migrar datos existentes (cooperative_id = NULL) ──
        tables = [
            (Route, "routes", Route.cooperative_id),
            (Stop, "stops", Stop.cooperative_id),
            (BusPosition, "bus_positions", BusPosition.cooperative_id),
            (Driver, "drivers", Driver.cooperative_id),
        ]
        for model, table_name, column in tables:
            stmt = update(model).where(column.is_(None)).values(cooperative_id=coop_id)
            result = await db.execute(stmt)
            print(f"Migrados {result.rowcount} registros en '{table_name}'")

        await db.commit()
        print("\n✅ Migración Multi-Tenant completada.")
        print(f"   Todas las entidades ahora pertenecen a '{DEFAULT_COOPERATIVE_NAME}' (ID={coop_id}).")


if __name__ == "__main__":
    asyncio.run(migrate())