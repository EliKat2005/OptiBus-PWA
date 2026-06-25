"""
OptiBus Admin Dashboard — DevSecOps v4.0
Dashboard HTML accesible vía API Key (header Authorization, NO query param).
Separado de main.py para mantener modularidad.
"""

import logging
from datetime import UTC, datetime, timedelta

import models
from auth_utils import verify_api_key
from config import API_KEY_ENABLED, APP_VERSION
from database import get_db
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ws_manager import ConnectionManager

logger = logging.getLogger("optibus-admin")

router = APIRouter(tags=["admin"])

# WebSocket manager (inyectado desde main.py)
_ws_manager: ConnectionManager | None = None


def init_admin(ws_manager: ConnectionManager):
    """Inicializa el módulo con el ConnectionManager."""
    global _ws_manager
    _ws_manager = ws_manager


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """
    Dashboard admin accesible vía header Authorization: Bearer <token>.
    DevSecOps: NO acepta api_key como query param (evitar leaks en logs).
    """
    # Verificar autenticación vía header
    auth_header = request.headers.get("Authorization", "")
    authed = False

    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        from auth_utils import OPTIBUS_API_KEY, decode_jwt_token
        from secrets import compare_digest

        if API_KEY_ENABLED and compare_digest(token, OPTIBUS_API_KEY):
            authed = True
        else:
            try:
                payload = decode_jwt_token(token)
                if payload.get("type") == "access":
                    authed = True
            except Exception:
                pass

    if not authed:
        return JSONResponse(
            status_code=401,
            content={
                "detail": "Acceso denegado. Usa Authorization: Bearer <token> en el header."
            },
        )

    # ── Obtener estadísticas ──
    stats = {
        "routes": 0,
        "stops": 0,
        "positions": 0,
        "ws": _ws_manager.active_count if _ws_manager else 0,
    }
    try:
        r_count = await db.execute(select(func.count(models.Route.id)))
        stats["routes"] = r_count.scalar() or 0
        s_count = await db.execute(select(func.count(models.Stop.id)))
        stats["stops"] = s_count.scalar() or 0
        p_count = await db.execute(
            select(func.count(models.BusPosition.id)).where(
                models.BusPosition.recorded_at
                >= datetime.now(UTC) - timedelta(hours=24)
            )
        )
        stats["positions"] = p_count.scalar() or 0
    except Exception:
        pass

    return HTMLResponse(
        ADMIN_HTML_TEMPLATE.format(
            routes=stats["routes"],
            stops=stats["stops"],
            positions=stats["positions"],
            ws=stats["ws"],
            version=APP_VERSION,
            api_status="🔒 Habilitada" if API_KEY_ENABLED else "⚠️ Deshabilitada",
        )
    )


# ─── Template HTML (sin cambios visuales, solo eliminado el query param) ───

ADMIN_HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OptiBus Admin Dashboard</title>
    <style>
        *{{margin:0;padding:0;box-sizing:border-box}}
        body{{font-family:system-ui,sans-serif;background:#0f172a;color:#e2e8f0;padding:20px}}
        h1{{text-align:center;margin-bottom:20px;color:#38bdf8}}
        .grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(280px,1fr));gap:16px;max-width:1200px;margin:0 auto}}
        .card{{background:#1e293b;border-radius:12px;padding:20px;border:1px solid #334155}}
        .card h2{{font-size:1rem;color:#94a3b8;margin-bottom:8px}}
        .card .value{{font-size:2rem;font-weight:bold;color:#38bdf8}}
        .card .sub{{font-size:.8rem;color:#64748b;margin-top:4px}}
        table{{width:100%;border-collapse:collapse;margin-top:12px}}
        th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #334155}}
        th{{color:#94a3b8;font-weight:600;font-size:.8rem}}
        td{{font-size:.9rem}}
        .badge{{display:inline-block;padding:2px 8px;border-radius:12px;font-size:.75rem}}
        .badge-active{{background:#065f46;color:#6ee7b7}}
        .status-bar{{display:flex;gap:16px;justify-content:center;margin-bottom:20px;flex-wrap:wrap}}
        .status-dot{{width:10px;height:10px;border-radius:50%;display:inline-block;margin-right:6px}}
        .status-dot.ok{{background:#10b981}}
        .status-dot.err{{background:#ef4444}}
        #alert-box{{background:#7f1d1d;border:1px solid #ef4444;padding:12px;border-radius:8px;margin-top:16px;display:none}}
        .route-badge{{background:#1e40af;color:#93c5fd;padding:2px 8px;border-radius:6px;font-size:.75rem}}
        .auth-badge{{background:#1e293b;border:1px solid #334155;padding:4px 12px;border-radius:6px;font-size:.8rem;color:#94a3b8}}
    </style>
</head>
<body>
    <h1>🚌 OptiBus Admin Dashboard</h1>
    <div class="status-bar">
        <span class="auth-badge">🔑 Auth: Header Authorization solo</span>
        <span id="statusBar"></span>
    </div>
    <div class="grid">
        <div class="card"><h2>🚌 Buses Activos</h2><div class="value" id="activeBuses">-</div><div class="sub">Últimos 5 minutos</div></div>
        <div class="card"><h2>🔌 WebSocket</h2><div class="value">{ws}</div><div class="sub">Conexiones activas</div></div>
        <div class="card"><h2>📡 Posiciones (24h)</h2><div class="value">{positions}</div><div class="sub">Registros GPS guardados</div></div>
        <div class="card"><h2>🛡️ API Key</h2><div class="value">{api_status}</div><div class="sub">Estado de autenticación</div></div>
    </div>
    <div class="card" style="max-width:1200px;margin:16px auto">
        <h2>📍 Buses Activos Ahora</h2>
        <div style="overflow-x:auto"><table><thead><tr><th>Bus ID</th><th>Latitud</th><th>Longitud</th><th>Velocidad</th><th>Última vez</th></tr></thead><tbody id="busesTable"></tbody></table></div>
    </div>
    <div id="alert-box">⚠️ <span id="alertMessage"></span></div>
    <script>
        // DevSecOps: NO usamos api_key como query param. El admin ya pasó auth via header.
        async function loadData(){{
            try{{
                const h=await fetch('/health');const hd=await h.json();
                document.getElementById('statusBar').innerHTML=
                    `<span><span class="status-dot ${{hd.database==='connected'?'ok':'err'}}"></span>DB: ${{hd.database}}</span>`+
                    `<span><span class="status-dot ${{hd.redis==='connected'?'ok':'err'}}"></span>Redis: ${{hd.redis}}</span>`+
                    `<span>v${{hd.version}}</span>`;

                const ab=await fetch('/api/bus/active?minutes=5');const abd=await ab.json();
                document.getElementById('activeBuses').textContent=abd.active_count||0;
                const tb=document.getElementById('busesTable');
                tb.innerHTML=(abd.buses||[]).map(b=>
                    `<tr><td>${{b.bus_id}}</td><td>${{b.lat.toFixed(6)}}</td><td>${{b.lon.toFixed(6)}}</td><td>${{b.speed}} km/h</td><td>${{new Date(b.last_seen).toLocaleTimeString()}}</td></tr>`
                ).join('')||'<tr><td colspan="5">No hay buses activos</td></tr>';
            }}catch(e){{
                console.error(e);
                document.getElementById('activeBuses').textContent='Error';
            }}
        }}
        loadData();setInterval(loadData,10000);
    </script>
</body>
</html>"""