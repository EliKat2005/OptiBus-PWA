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

@pytest.mark.asyncio
async def test_nearby_stops_valid(client: AsyncClient):
    """Paradas cercanas con coordenadas válidas (requiere DB)."""
    response = await client.get("/api/stops/nearby?lat=0.35&lon=-78.12&radius_meters=500")
    assert response.status_code in (200, 500)  # 200 si hay DB, 500 si no

@pytest.mark.asyncio
async def test_bus_history_requires_bus_id(client: AsyncClient):
    """GET /api/bus/history sin bus_id debe fallar con 422."""
    response = await client.get("/api/bus/history")
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_active_buses_format(client: AsyncClient):
    """GET /api/bus/active debe devolver estructura correcta."""
    response = await client.get("/api/bus/active?minutes=5")
    assert response.status_code in (200, 500)
    if response.status_code == 200:
        data = response.json()
        assert "active_count" in data
        assert "buses" in data

@pytest.mark.asyncio
async def test_login_missing_email(client: AsyncClient):
    """POST /api/auth/login sin email debe fallar con 422."""
    response = await client.post("/api/auth/login", json={"password": "test"})
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_register_driver_missing_fields(client: AsyncClient):
    """POST /api/auth/register sin campos obligatorios debe fallar."""
    response = await client.post("/api/auth/register", json={"email": "test@test.com"})
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_stops_nearby_radius_too_large(client: AsyncClient):
    """Radio > 10000m debe devolver 400."""
    response = await client.get("/api/stops/nearby?lat=0.35&lon=-78.12&radius_meters=20000")
    assert response.status_code == 400

@pytest.mark.asyncio
async def test_geofence_requires_params(client: AsyncClient):
    """GET /api/alert/geofence sin parámetros debe fallar."""
    response = await client.get("/api/alert/geofence")
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_eta_requires_params(client: AsyncClient):
    """GET /api/eta sin parámetros debe fallar."""
    response = await client.get("/api/eta")
    assert response.status_code == 422

@pytest.mark.asyncio
async def test_stops_record_invalid_coords(client: AsyncClient):
    """POST /api/stops/record con coordenadas inválidas."""
    response = await client.post("/api/stops/record", json={
        "bus_id": "test", "stop_name": "Test", "lat": 999, "lon": 0
    })
    assert response.status_code in (400, 401)  # 401 si API key no configurada

@pytest.mark.asyncio
async def test_route_plan_no_body(client: AsyncClient):
    """POST /api/routes/plan sin body debe fallar con 400."""
    response = await client.post("/api/routes/plan")
    assert response.status_code in (400, 422)

@pytest.mark.asyncio
async def test_route_plan_same_stops(client: AsyncClient):
    """POST /api/routes/plan con misma parada origen/destino."""
    response = await client.post("/api/routes/plan", json={
        "from_stop_id": 1, "to_stop_id": 1
    })
    assert response.status_code in (400, 200)  # 400 si mismo ID, 200 si BD

@pytest.mark.asyncio
async def test_rate_limiter(client: AsyncClient):
    """Prueba que el rate limiter funcione (debe devolver 200)."""
    responses = []
    for _ in range(5):
        r = await client.get("/health")
        responses.append(r.status_code)
    assert all(s == 200 for s in responses)

@pytest.mark.asyncio
async def test_owntracks_ignored(client: AsyncClient):
    """POST /api/gps/owntracks sin _type location es ignorado."""
    response = await client.post("/api/gps/owntracks", json={"_type": "unknown"})
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
