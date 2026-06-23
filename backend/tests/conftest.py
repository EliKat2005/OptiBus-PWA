"""Fixtures de pytest con base de datos real para tests de integración."""

import os
import asyncio
import pytest
from httpx import AsyncClient, ASGITransport

# Forzar variables de entorno de test ANTES de importar la app
os.environ.setdefault("POSTGRES_DB", "optibus_test")
os.environ.setdefault("POSTGRES_USER", "optibus_test")
os.environ.setdefault("POSTGRES_PASSWORD", "testpass")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5433")
os.environ.setdefault("REDIS_URL", "redis://localhost:6380/0")
os.environ.setdefault("OPTIBUS_API_KEY", "test-key-32-chars-minimum!!")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:80,http://localhost")

from main import app
from database import engine, Base

@pytest.fixture(scope="session")
def event_loop():
    """Crear un único event loop para toda la sesión de tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()

@pytest.fixture(autouse=True)
async def setup_db():
    """Crear tablas antes de cada test y limpiarlas después."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

@pytest.fixture
async def client():
    """Cliente HTTP asíncrono apuntando a la app FastAPI."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.fixture
def auth_headers():
    """Headers de autenticación con API Key de test."""
    return {"Authorization": "Bearer test-key-32-chars-minimum!!"}