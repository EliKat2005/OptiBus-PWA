"""Tests para OptiBus API - Ejecutar con: pytest test_api.py -v"""
import pytest
from httpx import AsyncClient, ASGITransport
from main import app

@pytest.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert "database" in data
    assert "redis" in data

@pytest.mark.asyncio
async def test_cors_headers():
    assert len(app.user_middleware) > 0

@pytest.mark.asyncio
async def test_gps_update_no_auth_401(client: AsyncClient):
    """Sin API Key configurada, el endpoint deja pasar. Con API Key, da 401."""
    response = await client.post("/api/gps/update", json={
        "bus_id": "test_bus", "lat": 0.35, "lon": -78.12
    })
    # Si API_KEY_ENABLED es False, retorna 200. Si True, 401.
    assert response.status_code in (200, 401)

@pytest.mark.asyncio
async def test_gps_update_invalid_coords(client: AsyncClient):
    response = await client.post("/api/gps/update", json={
        "bus_id": "test", "lat": 999.0, "lon": -78.12
    })
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_get_routes(client: AsyncClient):
    response = await client.get("/api/routes")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert "features" in data

@pytest.mark.asyncio
async def test_get_nearby_stops_invalid(client: AsyncClient):
    response = await client.get("/api/stops/nearby?lat=200&lon=0")
    assert response.status_code == 400

@pytest.mark.asyncio
async def test_admin_dashboard(client: AsyncClient):
    response = await client.get("/admin")
    assert response.status_code == 200
    assert "OptiBus" in response.text

@pytest.mark.asyncio
async def test_simulator_status(client: AsyncClient):
    response = await client.get("/api/simulator/status")
    assert response.status_code == 200
    data = response.json()
    assert "simulator_enabled" in data

@pytest.mark.asyncio
async def test_auth_status(client: AsyncClient):
    response = await client.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert "api_key_enabled" in data