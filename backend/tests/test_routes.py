"""Tests de integración para endpoints de la API OptiBus."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.4.0"
    assert "database" in data
    assert "redis" in data


@pytest.mark.asyncio
async def test_get_routes_empty(client: AsyncClient):
    response = await client.get("/api/routes")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
    assert isinstance(data["features"], list)


@pytest.mark.asyncio
async def test_stops_nearby_invalid_coords(client: AsyncClient):
    response = await client.get("/api/stops/nearby?lat=200&lon=0")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_stops_nearby_valid_coords(client: AsyncClient):
    response = await client.get("/api/stops/nearby?lat=0.35&lon=-78.12&radius_meters=500")
    assert response.status_code == 200
    data = response.json()
    assert "nearby_stops" in data


@pytest.mark.asyncio
async def test_gps_update_no_auth(client: AsyncClient):
    response = await client.post("/api/gps/update", json={
        "bus_id": "test-bus", "lat": 0.35, "lon": -78.12
    })
    assert response.status_code in (200, 401)


@pytest.mark.asyncio
async def test_gps_update_invalid_coords(client: AsyncClient):
    response = await client.post("/api/gps/update", json={
        "bus_id": "test-bus", "lat": 999, "lon": 0
    })
    assert response.status_code == 422


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
    assert "active_ws_connections" in data


@pytest.mark.asyncio
async def test_auth_status(client: AsyncClient):
    response = await client.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["api_key_enabled"] is True


@pytest.mark.asyncio
async def test_login_missing_email(client: AsyncClient):
    response = await client.post("/api/auth/login", json={"password": "test"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_register_driver_missing_fields(client: AsyncClient):
    response = await client.post("/api/auth/register", json={"email": "test@test.com"})
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_bus_history_requires_bus_id(client: AsyncClient):
    response = await client.get("/api/bus/history")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_active_buses_format(client: AsyncClient):
    response = await client.get("/api/bus/active?minutes=5")
    assert response.status_code == 200
    data = response.json()
    assert "active_count" in data
    assert "buses" in data


@pytest.mark.asyncio
async def test_owntracks_ignored(client: AsyncClient):
    response = await client.post("/api/gps/owntracks", json={"_type": "unknown"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_stops_nearby_radius_too_large(client: AsyncClient):
    response = await client.get("/api/stops/nearby?lat=0.35&lon=-78.12&radius_meters=20000")
    assert response.status_code == 400


@pytest.mark.asyncio
async def test_geofence_requires_params(client: AsyncClient):
    response = await client.get("/api/alert/geofence")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_eta_requires_params(client: AsyncClient):
    response = await client.get("/api/eta")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_route_plan_no_body(client: AsyncClient):
    response = await client.post("/api/routes/plan")
    assert response.status_code in (400, 422)


@pytest.mark.asyncio
async def test_rate_limiter(client: AsyncClient):
    responses = []
    for _ in range(5):
        r = await client.get("/health")
        responses.append(r.status_code)
    assert all(s == 200 for s in responses)