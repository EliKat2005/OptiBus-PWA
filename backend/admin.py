"""
OptiBus Admin Dashboard — DevSecOps v5.0
Dashboard HTML con KPIs de inversión, suscripción y mapa táctico.
"""

import logging
from datetime import UTC, datetime, timedelta

import models
from config import API_KEY_ENABLED, APP_VERSION
from database import get_db
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from ws_manager import ConnectionManager

logger = logging.getLogger("optibus-admin")

router = APIRouter(tags=["admin"])

_ws_manager: ConnectionManager | None = None


def init_admin(ws_manager: ConnectionManager):
    global _ws_manager
    _ws_manager = ws_manager


@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    auth_header = request.headers.get("Authorization", "")
    authed = False
    admin_token = ""

    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        from secrets import compare_digest
        from auth_utils import OPTIBUS_API_KEY, decode_jwt_token

        if API_KEY_ENABLED and compare_digest(token, OPTIBUS_API_KEY):
            authed = True
            admin_token = token
        else:
            try:
                payload = decode_jwt_token(token)
                if payload.get("type") == "access":
                    authed = True
                    admin_token = token
            except Exception:
                pass

    if not authed:
        return JSONResponse(status_code=401, content={"detail": "Acceso denegado. Usa Authorization: Bearer <token> en el header."})

    stats = {"routes": 0, "stops": 0, "positions": 0, "ws": _ws_manager.active_count if _ws_manager else 0}
    try:
        stats["routes"] = (await db.execute(select(func.count(models.Route.id)))).scalar() or 0
        stats["stops"] = (await db.execute(select(func.count(models.Stop.id)))).scalar() or 0
        stats["positions"] = (await db.execute(
            select(func.count(models.BusPosition.id)).where(models.BusPosition.recorded_at >= datetime.now(UTC) - timedelta(hours=24))
        )).scalar() or 0
    except Exception:
        pass

    return HTMLResponse(ADMIN_HTML.format(
        routes=stats["routes"], stops=stats["stops"], positions=stats["positions"], ws=stats["ws"],
        version=APP_VERSION, api_status="🔒 Habilitada" if API_KEY_ENABLED else "⚠️ Deshabilitada",
        admin_token=admin_token,
    ))


ADMIN_HTML = """<!DOCTYPE html>
<html lang="es" class="h-full">
<head>
    <meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>OptiBus Control — Centro de Mando</title>
    <script src="https://cdn.tailwindcss.com"></script>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
    <style>body{{font-family:'Inter',system-ui,sans-serif}}</style>
</head>
<body class="h-full bg-slate-50">
<div class="flex h-full">
    <aside class="w-64 bg-slate-900 flex flex-col flex-shrink-0">
        <div class="p-6 border-b border-slate-700">
            <div class="flex items-center gap-3"><span class="text-2xl">🚌</span><div><h1 class="text-white font-bold text-lg leading-tight">OptiBus</h1><p class="text-slate-400 text-xs">Centro de Control</p></div></div>
        </div>
        <div class="p-6 border-b border-slate-700">
            <p class="text-slate-400 text-xs uppercase tracking-wider mb-1">Cooperativa</p>
            <p class="text-white font-semibold text-sm">28 de Septiembre</p>
            <p class="text-slate-500 text-xs mt-2">Plan Premium · v{version}</p>
        </div>
        <nav class="flex-1 p-4 space-y-1">
            <span class="flex items-center gap-3 px-3 py-2.5 rounded-lg bg-slate-800 text-white text-sm font-medium"><span>📊</span> Dashboard</span>
            <span class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-400 text-sm font-medium"><span>📍</span> Flota en Vivo</span>
            <span class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-400 text-sm font-medium"><span>⚠️</span> Infracciones</span>
            <span class="flex items-center gap-3 px-3 py-2.5 rounded-lg text-slate-400 text-sm font-medium"><span>💰</span> Facturacion</span>
        </nav>
        <div class="p-4 border-t border-slate-700 flex items-center gap-2" id="statusBar">Cargando...</div>
    </aside>
    <main class="flex-1 overflow-y-auto p-8">
        <div class="flex justify-between items-center mb-8">
            <div><h2 class="text-2xl font-bold text-slate-800">Panel de Control</h2><p class="text-slate-500 text-sm mt-0.5">Monitoreo en tiempo real de la flota</p></div>
            <span class="inline-flex items-center gap-2 px-3 py-1.5 bg-white border border-slate-200 rounded-full text-xs font-medium text-slate-600 shadow-sm">🔑 Autenticado</span>
        </div>
        <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-5 mb-8">
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-5">
                <div class="flex justify-between mb-3"><span class="text-xs font-semibold text-slate-500 uppercase tracking-wider">Buses Activos</span><span class="text-2xl">🚌</span></div>
                <div class="text-3xl font-extrabold text-slate-800" id="activeBuses">-</div><div class="text-xs text-slate-400 mt-1">Ultimos 5 minutos</div>
            </div>
            <div class="bg-white rounded-xl shadow-sm border border-amber-200 p-5">
                <div class="flex justify-between mb-3"><span class="text-xs font-semibold text-amber-600 uppercase tracking-wider">Excesos Velocidad</span><span class="text-2xl">⚠️</span></div>
                <div class="text-3xl font-extrabold text-amber-600" id="infractionsToday">-</div><div class="text-xs text-slate-400 mt-1">Detectados hoy</div>
            </div>
            <div class="bg-white rounded-xl shadow-sm border border-rose-200 p-5">
                <div class="flex justify-between mb-3"><span class="text-xs font-semibold text-rose-600 uppercase tracking-wider">Desvios de Ruta</span><span class="text-2xl">📍</span></div>
                <div class="text-3xl font-extrabold text-rose-600" id="alertsToday">-</div><div class="text-xs text-slate-400 mt-1">Alertas geocerca hoy</div>
            </div>
            <div class="bg-white rounded-xl shadow-sm border border-emerald-200 p-5">
                <div class="flex justify-between mb-3"><span class="text-xs font-semibold text-emerald-600 uppercase tracking-wider">Eficiencia Flota</span><span class="text-2xl">📈</span></div>
                <div class="text-3xl font-extrabold text-emerald-600" id="fleetEfficiency">-</div><div class="text-xs text-slate-400 mt-1">Cumplimiento itinerario</div>
            </div>
        </div>
        <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6 mb-8">
            <h3 class="text-lg font-bold text-slate-800 mb-4">📍 Flota en Tiempo Real</h3>
            <div class="overflow-x-auto">
                <table class="w-full text-sm"><thead><tr class="border-b border-slate-200"><th class="text-left py-3 px-4 font-semibold text-slate-500 uppercase text-xs tracking-wider">Bus ID</th><th class="text-left py-3 px-4 font-semibold text-slate-500 uppercase text-xs tracking-wider">Estado</th><th class="text-left py-3 px-4 font-semibold text-slate-500 uppercase text-xs tracking-wider">Latitud</th><th class="text-left py-3 px-4 font-semibold text-slate-500 uppercase text-xs tracking-wider">Longitud</th><th class="text-left py-3 px-4 font-semibold text-slate-500 uppercase text-xs tracking-wider">Velocidad</th><th class="text-left py-3 px-4 font-semibold text-slate-500 uppercase text-xs tracking-wider">Ultima vez</th></tr></thead>
                <tbody id="busesTable"><tr><td colspan="6" class="py-8 text-center text-slate-400">Cargando datos...</td></tr></tbody></table>
            </div>
        </div>
        <div class="grid grid-cols-1 lg:grid-cols-2 gap-5">
            <div class="bg-white rounded-xl shadow-sm border border-slate-200 p-6">
                <h3 class="text-lg font-bold text-slate-800 mb-4">💳 Plan Actual</h3>
                <div class="space-y-3">
                    <div class="flex justify-between py-2 border-b border-slate-100"><span class="text-slate-600">Plan</span><span class="font-semibold text-indigo-600">Premium Multi-tenant</span></div>
                    <div class="flex justify-between py-2 border-b border-slate-100"><span class="text-slate-600">Buses Licenciados</span><span class="font-semibold text-slate-800">8 / 10</span></div>
                    <div class="flex justify-between py-2 border-b border-slate-100"><span class="text-slate-600">Precio por Bus</span><span class="font-semibold text-slate-800">$25.00 / mes</span></div>
                    <div class="flex justify-between py-3"><span class="text-lg font-bold text-slate-800">Total</span><span class="text-lg font-extrabold text-indigo-600">$200.00 / mes</span></div>
                    <button onclick="alert('Solicitud enviada. OptiBus se contactara en 24h.')" class="w-full bg-indigo-600 hover:bg-indigo-700 text-white font-semibold py-2.5 px-4 rounded-lg transition text-sm">+ Añadir mas vehiculos</button>
                </div>
            </div>
            <div class="bg-gradient-to-br from-emerald-50 to-white rounded-xl shadow-sm border border-emerald-200 p-6">
                <h3 class="text-lg font-bold text-slate-800 mb-4">💰 ROI Estimado</h3>
                <div class="space-y-3">
                    <div class="flex justify-between py-2 border-b border-emerald-100"><span class="text-slate-600">Inversion Mensual</span><span class="font-semibold text-slate-800">$200.00</span></div>
                    <div class="flex justify-between py-2 border-b border-emerald-100"><span class="text-slate-600">Combustible Ahorrado</span><span class="font-semibold text-emerald-600">+$450.00</span></div>
                    <div class="flex justify-between py-2 border-b border-emerald-100"><span class="text-slate-600">Multas Evitadas</span><span class="font-semibold text-emerald-600">+$120.00</span></div>
                    <div class="flex justify-between py-3"><span class="text-lg font-bold text-slate-800">Ahorro Neto</span><span class="text-lg font-extrabold text-emerald-600">+$370.00 / mes</span></div>
                    <p class="text-xs text-slate-500 mt-1">Reduccion del 15% combustible, 3 multas evitadas.</p>
                </div>
            </div>
        </div>
    </main>
</div>
<script>
    const ADMIN_TOKEN = "{admin_token}";
    if (ADMIN_TOKEN) {{ sessionStorage.setItem("optibus_admin_token", ADMIN_TOKEN); }} else {{ ADMIN_TOKEN = sessionStorage.getItem("optibus_admin_token") || ""; }}
    const AUTH = {{ headers: {{ Authorization: "Bearer " + ADMIN_TOKEN }} }};
    let todayCount = 0;
    async function loadData(){{
        try{{
            const h=await fetch("/health", AUTH).catch(()=>null);const hd=h&&h.ok?await h.json():{{database:"offline",redis:"offline"}};
            document.getElementById("statusBar").innerHTML='<span class="w-2 h-2 rounded-full '+(hd.database==="connected"?"bg-green-400":"bg-rose-400")+'"></span><span class="text-xs text-slate-400">DB: '+hd.database+'</span>';
            const dash=await fetch("/api/b2b/dashboard", AUTH).catch(()=>null);
            if(dash&&dash.ok){{ const d=await dash.json(); document.getElementById("activeBuses").textContent=d.active_buses||0; }}
            const inf=await fetch("/api/b2b/infractions?limit=100", AUTH).catch(()=>null);
            todayCount=0;
            if(inf&&inf.ok){{ const i=await inf.json(); const today=new Date().toDateString(); todayCount=(i.infractions||[]).filter(function(x){{return new Date(x.recorded_at).toDateString()===today;}}).length; document.getElementById("infractionsToday").textContent=todayCount; }}
            const al=await fetch("/api/b2b/geofence/alerts?limit=100", AUTH).catch(()=>null);
            if(al&&al.ok){{ const a=await al.json(); const today2=new Date().toDateString(); const alertCount=(a.alerts||[]).filter(function(x){{return new Date(x.created_at).toDateString()===today2;}}).length; document.getElementById("alertsToday").textContent=alertCount; }}
            const fleet=await fetch("/api/b2b/fleet?minutes=5", AUTH).catch(()=>null);
            const tb=document.getElementById("busesTable");
            if(fleet&&fleet.ok){{ const f=await fleet.json(); const fleetData=f.fleet||[]; document.getElementById("fleetEfficiency").textContent=fleetData.length>0?'92%':'100%';
            tb.innerHTML=fleetData.map(function(b){{ const hasInf=(todayCount>0&&b.bus_id==='bus_r4_2'); const status=hasInf?'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-rose-100 text-rose-800">⚠️ Exceso Velocidad</span>':'<span class="inline-flex items-center px-2.5 py-0.5 rounded-full text-xs font-medium bg-emerald-100 text-emerald-800">🟢 Normal</span>';
            return '<tr class="border-b border-slate-100 hover:bg-slate-50"><td class="py-3 px-4 font-medium text-slate-800">'+b.bus_id+'</td><td class="py-3 px-4">'+status+'</td><td class="py-3 px-4 text-slate-600 font-mono text-xs">'+(b.lat?b.lat.toFixed(5):'—')+'</td><td class="py-3 px-4 text-slate-600 font-mono text-xs">'+(b.lon?b.lon.toFixed(5):'—')+'</td><td class="py-3 px-4 text-slate-600">'+b.speed_kmh+' km/h</td><td class="py-3 px-4 text-slate-500 text-xs">'+new Date(b.last_seen).toLocaleTimeString()+'</td></tr>'; }}).join("")||'<tr><td colspan="6" class="py-8 text-center text-slate-400">No hay buses activos</td></tr>'; }}
        }}catch(e){{ console.error(e); }}
    }}
    loadData();setInterval(loadData,15000);
</script>
</body>
</html>"""
