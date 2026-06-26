"""Tests de integración para endpoints de la API OptiBus v4.0."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_health_check(client: AsyncClient):
    response = await client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "0.5.0"
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
    response = await client.get(
        "/api/stops/nearby?lat=0.35&lon=-78.12&radius_meters=500"
    )
    assert response.status_code == 200
    data = response.json()
    assert "nearby_stops" in data


@pytest.mark.asyncio
async def test_gps_update_no_auth(client: AsyncClient):
    """Sin auth, debe rechazar el acceso."""
    response = await client.post(
        "/api/gps/update",
        json={"bus_id": "test-bus", "lat": 0.35, "lon": -78.12},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_gps_update_invalid_coords(client: AsyncClient):
    response = await client.post(
        "/api/gps/update",
        json={"bus_id": "test-bus", "lat": 999, "lon": 0},
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_gps_update_with_auth(client: AsyncClient, auth_headers):
    """Con auth válida, debe aceptar."""
    response = await client.post(
        "/api/gps/update",
        json={"bus_id": "test-bus", "lat": 0.35, "lon": -78.12},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "success"


@pytest.mark.asyncio
async def test_admin_dashboard_no_auth(client: AsyncClient):
    """Sin auth, debe rechazar (ya no acepta query param)."""
    response = await client.get("/admin")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_admin_dashboard_with_auth(client: AsyncClient, auth_headers):
    """Con auth por header, debe funcionar."""
    response = await client.get("/admin", headers=auth_headers)
    assert response.status_code == 200
    assert "OptiBus" in response.text


@pytest.mark.asyncio
async def test_simulator_status_with_auth(client: AsyncClient, auth_headers):
    response = await client.get("/api/simulator/status", headers=auth_headers)
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
async def test_login_invalid_credentials(client: AsyncClient):
    response = await client.post(
        "/api/auth/login",
        json={"email": "noexiste@test.com", "password": "wrong"},
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_register_driver_with_auth(client: AsyncClient, auth_headers):
    """Admin registra un conductor."""
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "driver1@test.com",
            "password": "SecurePass123!",
            "name": "Test Driver",
            "bus_id": "BUS-001",
        },
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "created"
    assert data["driver"]["email"] == "driver1@test.com"


@pytest.mark.asyncio
async def test_login_success(client: AsyncClient, auth_headers):
    """Registrar + login exitoso."""
    # Registrar primero
    await client.post(
        "/api/auth/register",
        json={
            "email": "login@test.com",
            "password": "TestPass123!",
            "name": "Login Test",
            "bus_id": "BUS-LOGIN",
        },
        headers=auth_headers,
    )
    # Login
    response = await client.post(
        "/api/auth/login",
        json={"email": "login@test.com", "password": "TestPass123!"},
    )
    assert response.status_code == 200
    data = response.json()
    assert "access_token" in data
    assert "refresh_token" in data
    assert data["driver"]["email"] == "login@test.com"


@pytest.mark.asyncio
async def test_register_driver_unauthorized(client: AsyncClient):
    """Sin auth, no debe permitir registro."""
    response = await client.post(
        "/api/auth/register",
        json={
            "email": "hacker@test.com",
            "password": "pass",
            "name": "Hacker",
        },
    )
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_bus_history_requires_bus_id(client: AsyncClient):
    response = await client.get("/api/bus/history")
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_active_buses_format(client: AsyncClient, auth_headers):
    response = await client.get("/api/bus/active?minutes=5", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert "active_count" in data
    assert "buses" in data


@pytest.mark.asyncio
async def test_owntracks_ignored(client: AsyncClient, auth_headers):
    response = await client.post(
        "/api/gps/owntracks",
        json={"_type": "unknown"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"


@pytest.mark.asyncio
async def test_stops_nearby_radius_too_large(client: AsyncClient):
    response = await client.get(
        "/api/stops/nearby?lat=0.35&lon=-78.12&radius_meters=20000"
    )
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
    """Rate limiter no debe bloquear peticiones legítimas."""
    responses = []
    for _ in range(5):
        r = await client.get("/health")
        responses.append(r.status_code)
    assert all(s == 200 for s in responses)


@pytest.mark.asyncio
async def test_auth_me_with_api_key(client: AsyncClient, auth_headers):
    """GET /api/auth/me con API Key retorna admin info."""
    response = await client.get("/api/auth/me", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["role"] == "admin"
    assert data["auth_type"] == "api_key"


@pytest.mark.asyncio
async def test_forgot_password(client: AsyncClient, auth_headers):
    """Solicita recuperación de contraseña."""
    # Registrar driver primero
    await client.post(
        "/api/auth/register",
        json={
            "email": "forgot@test.com",
            "password": "OldPass123!",
            "name": "Forgot Me",
        },
        headers=auth_headers,
    )
    response = await client.post(
        "/api/auth/forgot-password",
        json={"email": "forgot@test.com"},
        headers=auth_headers,
    )
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    # El admin ve el reset_token
    assert "reset_token_admin" in data
    assert len(data["reset_token_admin"]) > 10
