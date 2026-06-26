"""Fixtures de pytest con base de datos real para tests de integración v4.1."""

import os

import pytest
from httpx import ASGITransport, AsyncClient

# Forzar variables de entorno de test ANTES de importar la app
os.environ.setdefault("POSTGRES_DB", "optibus_test")
os.environ.setdefault("POSTGRES_USER", "optibus")
os.environ.setdefault("POSTGRES_PASSWORD", "testpass")
os.environ.setdefault("POSTGRES_HOST", "localhost")
os.environ.setdefault("POSTGRES_PORT", "5432")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("OPTIBUS_API_KEY", "test-key-32-chars-minimum!!")
os.environ.setdefault("JWT_SECRET", "test-jwt-secret-32-chars-minimum!!")
os.environ.setdefault("CORS_ORIGINS", "http://localhost:80,http://localhost")

from database import Base, engine
from main import app


@pytest.fixture(scope="session")
def event_loop_policy():
    """Usar la política de event loop por defecto para evitar conflictos."""
    import asyncio
    return asyncio.DefaultEventLoopPolicy()


@pytest.fixture(scope="module", autouse=True)
async def setup_db():
    """Crear tablas antes de los tests del módulo y limpiarlas después."""
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


@pytest.fixture
def jwt_token_headers():
    """Headers con JWT access token para un driver de prueba."""
    from auth_utils import create_jwt_token

    token = create_jwt_token(
        driver_id=1, bus_id="TEST-BUS", role="driver", token_type="access"
    )
    return {"Authorization": f"Bearer {token}"}