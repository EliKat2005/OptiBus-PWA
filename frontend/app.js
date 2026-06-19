// ======================================================================
// OptiBus-PWA v1.0 — Mobile-First con Chips y Dark Mode Funcional
// ======================================================================

const CONFIG = {
    center: [-0.2188, -78.5124],
    defaultZoom: 14,
    maxBusMarkers: 50,
    routeColors: [
        '#2563eb', '#dc2626', '#16a34a', '#ca8a04', '#9333ea',
        '#0891b2', '#e11d48', '#65a30d', '#d97706', '#7c3aed'
    ],
    routeOpacity: 0.85,
    routeWeight: 4,
    stopIconSize: 28,
    busIconSize: 36,
    arrowInterval: 8,
};

const API_URL = '';
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${wsProtocol}//${window.location.host}/ws`;

// ── Mapa ──
const map = L.map('map', {
    center: CONFIG.center,
    zoom: CONFIG.defaultZoom,
    zoomControl: true,
    attributionControl: true
});
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · OptiBus'
}).addTo(map);

// ── Capas ──
const routeLayers = {};
const stopMarkers = [];
const busMarkers = {};
const busTrails = {};
let currentDetailRouteId = null;
let activeFilterRouteId = null;
let routesGeoJSON = null;

const stopListEl = document.getElementById('stopList');

// ── Iconos ──
function createStopIcon(stopNumber, routeColor) {
    return L.divIcon({
        className: 'stop-icon',
        html: `<div class="stop-marker" style="--color: ${routeColor}">
                 <span class="stop-number">${stopNumber}</span>
                 <div class="stop-pulse"></div>
               </div>`,
        iconSize: [CONFIG.stopIconSize, CONFIG.stopIconSize],
        iconAnchor: [CONFIG.stopIconSize / 2, CONFIG.stopIconSize / 2],
        popupAnchor: [0, -CONFIG.stopIconSize / 2]
    });
}

function createBusIcon(bearing) {
    const rotation = bearing || 0;
    return L.divIcon({
        className: 'bus-icon',
        html: `<div class="bus-marker" style="transform: rotate(${rotation}deg)">
                 <svg viewBox="0 0 24 24" width="${CONFIG.busIconSize}" height="${CONFIG.busIconSize}">
                   <circle cx="12" cy="12" r="10" fill="#2563eb" stroke="#fff" stroke-width="2"/>
                   <path d="M8 12l3-3M8 12l3 3M8 12h8" stroke="#fff" stroke-width="2" stroke-linecap="round" fill="none"/>
                 </svg>
                 <div class="bus-id-label"></div>
               </div>`,
        iconSize: [CONFIG.busIconSize, CONFIG.busIconSize + 16],
        iconAnchor: [CONFIG.busIconSize / 2, CONFIG.busIconSize / 2 + 8],
        popupAnchor: [0, -CONFIG.busIconSize / 2]
    });
}

// ── Carga de rutas ──
async function loadRoutes() {
    try {
        const response = await fetch(`${API_URL}/api/routes`);
        if (!response.ok) throw new Error(`HTTP ${response.status}`);
        const geojsonData = await response.json();
        renderRoutes(geojsonData);
    } catch (error) {
        console.error('Error cargando rutas:', error);
    }
}

function renderRoutes(geojsonData) {
    routesGeoJSON = geojsonData;
    stopListEl.innerHTML = '';
    stopMarkers.length = 0;

    if (!geojsonData.features || geojsonData.features.length === 0) {
        stopListEl.innerHTML = '<div class="empty-state">🚏 Sin rutas configuradas</div>';
        return;
    }

    let allBounds = null;

    geojsonData.features.forEach((feature, routeIndex) => {
        const routeId = feature.properties.id;
        const routeName = feature.properties.name;
        const color = CONFIG.routeColors[routeIndex % CONFIG.routeColors.length];
        const coords = feature.geometry.coordinates;
        if (!coords || coords.length < 2) return;

        // Capa de ruta (sin paradas)
        const layerGroup = L.layerGroup().addTo(map);
        routeLayers[routeId] = layerGroup;

        L.polyline(coords.map(c => [c[1], c[0]]), {
            color: color, weight: CONFIG.routeWeight + 4, opacity: 0.15,
            smoothFactor: 2, interactive: false
        }).addTo(layerGroup);

        const mainLine = L.polyline(coords.map(c => [c[1], c[0]]), {
            color: color, weight: CONFIG.routeWeight, opacity: CONFIG.routeOpacity,
            smoothFactor: 2, lineCap: 'round', lineJoin: 'round'
        }).addTo(layerGroup);

        for (let i = CONFIG.arrowInterval; i < coords.length - 1; i += CONFIG.arrowInterval) {
            const p1 = coords[i], p2 = coords[i + 1];
            const midLat = (p1[0] + p2[0]) / 2, midLon = (p1[1] + p2[1]) / 2;
            const angle = Math.atan2(p2[0] - p1[0], p2[1] - p1[1]) * 180 / Math.PI + 90;
            L.marker([midLat, midLon], {
                icon: L.divIcon({
                    className: 'route-arrow-icon',
                    html: `<div class="route-arrow" style="--color: ${color}; transform: rotate(${angle}deg)">▶</div>`,
                    iconSize: [16, 16], iconAnchor: [8, 8]
                }), interactive: false
            }).addTo(layerGroup);
        }

        mainLine.bindTooltip(`<strong>${escapeHtml(routeName)}</strong>`, {
            sticky: true, direction: 'top', className: 'route-tooltip'
        });

        const routeBounds = mainLine.getBounds();
        if (!allBounds) allBounds = routeBounds; else allBounds.extend(routeBounds);
    });

    stopListEl.innerHTML = '<div class="empty-state" id="stopList-empty">Selecciona una ruta para ver sus paradas</div>';

    if (allBounds) {
        map.fitBounds(allBounds, { padding: [50, 50], maxZoom: 16 });
    }

    buildSearchIndex(geojsonData);
    populateRouteFilter(geojsonData);
    renderFavoritesList();
}

// ── Vista Detalle de Ruta (activado por chips y search) ──
function showRouteDetail(routeId) {
    if (!routesGeoJSON) return;
    currentDetailRouteId = routeId;

    const feature = routesGeoJSON.features.find(f => f.properties.id === routeId);
    if (!feature) return;

    const routeName = feature.properties.name;
    const stops = feature.properties.stops || [];
    const routeIndex = routesGeoJSON.features.indexOf(feature);
    const color = CONFIG.routeColors[routeIndex % CONFIG.routeColors.length];

    // ── Marcar chip como activo ──
    document.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
    const activeChip = document.querySelector(`.filter-chip[data-routeid="${routeId}"]`);
    if (activeChip) activeChip.classList.add('active');

    // ── Atenuar otras rutas ──
    Object.entries(routeLayers).forEach(([id, lg]) => {
        if (parseInt(id) === routeId) {
            lg.eachLayer(l => {
                if (l instanceof L.Polyline && l.options.color) {
                    l.setStyle({ opacity: 1, weight: CONFIG.routeWeight + 2 });
                }
            });
        } else {
            lg.eachLayer(l => {
                if (l instanceof L.Polyline && l.options.color) {
                    l.setStyle({ opacity: 0.08, weight: 1 });
                }
            });
        }
    });

    // ── Mostrar paradas en mapa ──
    hideAllStopMarkers();
    showStopMarkersForRoute(routeId, stops, color);

    // ── Panel inferior: título + lista de paradas ──
    stopListEl.innerHTML = '';
    const titleDiv = document.createElement('div');
    titleDiv.className = 'stop-list-title';
    titleDiv.innerHTML = `<span class="chip-dot" style="background:${color}"></span>${stops.length} Paradas`;
    stopListEl.appendChild(titleDiv);

    if (stops.length > 0) {
        stops.forEach((stop, idx) => {
            const stopItem = document.createElement('div');
            stopItem.className = 'stop-list-item';
            stopItem.innerHTML = `
                <span class="stop-list-number" style="background:${color}">${idx + 1}</span>
                <span class="stop-list-name">${escapeHtml(stop.name || `Parada ${idx + 1}`)}</span>
            `;
            stopItem.addEventListener('click', () => {
                map.setView([stop.lat, stop.lon], 17, { animate: true, duration: 0.6 });
            });
            stopListEl.appendChild(stopItem);
        });
    } else {
        stopListEl.innerHTML += '<div class="empty-state">Sin paradas registradas</div>';
    }

    stopListEl.scrollIntoView({ behavior: 'smooth', block: 'start' });
    centerOnRoute(routeId);
}

function showRouteOverview() {
    currentDetailRouteId = null;

    // ── Restaurar chips ──
    const chipsEl = document.getElementById('route-filter-chips');
    if (chipsEl) {
        chipsEl.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
        const allChip = chipsEl.querySelector('[data-routeid="all"]');
        if (allChip) allChip.classList.add('active');
    }
    activeFilterRouteId = null;

    // ── Restaurar rutas ──
    Object.values(routeLayers).forEach(lg => {
        lg.eachLayer(l => {
            if (l instanceof L.Polyline && l.options.color) {
                l.setStyle({ opacity: CONFIG.routeOpacity, weight: CONFIG.routeWeight });
            }
        });
    });

    hideAllStopMarkers();
    stopListEl.innerHTML = '<div class="empty-state" id="stopList-empty">Selecciona una ruta para ver sus paradas</div>';

    const bounds = getAllRoutesBounds();
    if (bounds.isValid()) map.fitBounds(bounds, { padding: [50, 50], maxZoom: 16 });
}

function hideAllStopMarkers() {
    stopMarkers.forEach(sm => { if (sm.marker && sm.marker._map) map.removeLayer(sm.marker); });
    stopMarkers.length = 0;
}

function showStopMarkersForRoute(routeId, stops, color) {
    stops.forEach((stop, index) => {
        const marker = L.marker([stop.lat, stop.lon], {
            icon: createStopIcon(index + 1, color),
            zIndexOffset: 500
        });
        marker.bindPopup(`
            <div class="stop-popup">
                <h3>🚏 ${escapeHtml(stop.name || `Parada ${index + 1}`)}</h3>
                <div class="popup-info">
                    <span>📍 ${stop.lat.toFixed(5)}, ${stop.lon.toFixed(5)}</span>
                </div>
            </div>
        `, { maxWidth: 260, className: 'custom-popup' });
        marker.bindTooltip(`<strong>${escapeHtml(stop.name || `Parada ${index + 1}`)}</strong>`, {
            direction: 'top', offset: [0, -18], className: 'stop-tooltip'
        });
        marker.addTo(map);
        stopMarkers.push({ marker, routeId, name: stop.name, coords: [stop.lat, stop.lon] });
    });
}

function centerOnRoute(routeId) {
    const lg = routeLayers[routeId];
    if (lg) {
        const bounds = L.latLngBounds();
        lg.eachLayer(l => { if (l instanceof L.Polyline) l.getLatLngs().forEach(ll => bounds.extend(ll)); });
        map.fitBounds(bounds, { padding: [80, 80], maxZoom: 16 });
    }
}

function getAllRoutesBounds() {
    const bounds = L.latLngBounds();
    Object.values(routeLayers).forEach(lg => {
        lg.eachLayer(l => { if (l instanceof L.Polyline) l.getLatLngs().forEach(ll => bounds.extend(ll)); });
    });
    return bounds;
}

// ── WebSocket ──
let wsReconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;
let wsInstance = null;
let pingTimer = null;
const busLastPos = {};

function connectWebSocket() {
    if (wsInstance && wsInstance.readyState !== WebSocket.CLOSED) wsInstance.close();
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
    const ws = new WebSocket(WS_URL);
    wsInstance = ws;
    ws.onopen = () => {
        updateConnectionStatus(true);
        wsReconnectDelay = 1000;
        pingTimer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify({ type: "ping" }));
        }, 30000);
    };
    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === "bus_positions" && Array.isArray(data.buses)) {
                data.buses.forEach(bus => {
                    if (typeof bus.lat !== 'number' || typeof bus.lon !== 'number' || bus.lat < -90 || bus.lat > 90 || bus.lon < -180 || bus.lon > 180) return;
                    let bearing = 0;
                    const last = busLastPos[bus.id];
                    if (last && (bus.lat !== last.lat || bus.lon !== last.lon)) {
                        const dLon = (bus.lon - last.lon) * Math.PI / 180;
                        const y = Math.sin(dLon) * Math.cos(bus.lat * Math.PI / 180);
                        const x = Math.cos(last.lat * Math.PI / 180) * Math.sin(bus.lat * Math.PI / 180) - Math.sin(last.lat * Math.PI / 180) * Math.cos(bus.lat * Math.PI / 180) * Math.cos(dLon);
                        bearing = Math.atan2(y, x) * 180 / Math.PI;
                    }
                    busLastPos[bus.id] = { lat: bus.lat, lon: bus.lon, timestamp: Date.now() };
                    if (busMarkers[bus.id]) {
                        busMarkers[bus.id].setLatLng([bus.lat, bus.lon]);
                        busMarkers[bus.id].setIcon(createBusIcon(bearing));
                        if (busTrails[bus.id]) {
                            busTrails[bus.id].addLatLng([bus.lat, bus.lon]);
                            const latlngs = busTrails[bus.id].getLatLngs();
                            if (latlngs.length > 20) busTrails[bus.id].setLatLngs(latlngs.slice(-20));
                        }
                    } else {
                        if (Object.keys(busMarkers).length >= CONFIG.maxBusMarkers) return;
                        const marker = L.marker([bus.lat, bus.lon], { icon: createBusIcon(0), zIndexOffset: 1000 }).addTo(map);
                        const sourceLabel = bus.source === 'real' ? '📡 GPS Real' : '🔄 Simulación';
                        marker.bindPopup(`<div class="bus-popup"><h3>🚌 ${escapeHtml(bus.id)}</h3><div class="popup-info"><span>📍 ${bus.lat.toFixed(6)}, ${bus.lon.toFixed(6)}</span><span>🔗 ${escapeHtml(sourceLabel)}</span></div></div>`, { maxWidth: 260, className: 'custom-popup' });
                        busMarkers[bus.id] = marker;
                        const trail = L.polyline([[bus.lat, bus.lon]], { color: '#2563eb', weight: 2, opacity: 0.4, dashArray: '5 10', interactive: false }).addTo(map);
                        busTrails[bus.id] = trail;
                    }
                });
                const now = Date.now();
                Object.entries(busLastPos).forEach(([id, pos]) => {
                    if (now - pos.timestamp > 60000) {
                        if (busMarkers[id]) { map.removeLayer(busMarkers[id]); delete busMarkers[id]; }
                        if (busTrails[id]) { map.removeLayer(busTrails[id]); delete busTrails[id]; }
                        delete busLastPos[id];
                    }
                });
            }
        } catch (err) { console.error('Error WS:', err); }
    };
    ws.onclose = () => {
        if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
        updateConnectionStatus(false);
        setTimeout(connectWebSocket, wsReconnectDelay);
        wsReconnectDelay = Math.min(wsReconnectDelay * 2, MAX_RECONNECT_DELAY);
    };
}

let connectionHideTimer = null;
function updateConnectionStatus(connected) {
    const el = document.getElementById('connection-status');
    const textEl = document.getElementById('connection-text');
    if (!el || !textEl) return;
    if (connectionHideTimer) clearTimeout(connectionHideTimer);
    el.style.opacity = '1';
    if (connected) {
        el.className = 'connection-status connected';
        textEl.textContent = '🟢 Conectado';
        connectionHideTimer = setTimeout(() => { el.style.opacity = '0'; }, 3000);
    } else {
        el.className = 'connection-status lost';
        textEl.textContent = '🔴 Sin conexión';
        connectionHideTimer = setTimeout(() => { el.style.opacity = '0.5'; }, 10000);
    }
}

// ── Utilidades ──
function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// ── GPS cercano ──
async function findNearbyStops() {
    if (!navigator.geolocation) { alert('Tu navegador no soporta geolocalización'); return; }
    const gpsBtn = document.getElementById('btn-gps');
    if (gpsBtn) gpsBtn.classList.add('searching');
    navigator.geolocation.getCurrentPosition(async (position) => {
        const userLat = position.coords.latitude;
        const userLon = position.coords.longitude;
        if (!isFinite(userLat) || !isFinite(userLon) || userLat < -90 || userLat > 90 || userLon < -180 || userLon > 180) {
            alert('Coordenadas GPS inválidas.'); if (gpsBtn) gpsBtn.classList.remove('searching'); return;
        }
        map.setView([userLat, userLon], 16, { animate: true });
        L.marker([userLat, userLon], {
            icon: L.divIcon({ className: 'my-location-icon', html: '<div class="my-location-dot"></div>', iconSize: [20, 20], iconAnchor: [10, 10] })
        }).addTo(map).bindPopup('<b>📍 Estás aquí</b>').openPopup();
        try {
            const params = new URLSearchParams({ lat: userLat.toString(), lon: userLon.toString(), radius_meters: '300' });
            const response = await fetch(`${API_URL}/api/stops/nearby?${params}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);
            const data = await response.json();
            if (!data.nearby_stops || data.nearby_stops.length === 0) { alert('No hay paradas cercanas a tu ubicación (radio: 300 metros).'); return; }
            data.nearby_stops.forEach((stop, idx) => {
                if (!stop.geometry || !Array.isArray(stop.geometry.coordinates)) return;
                const stopLat = stop.geometry.coordinates[1], stopLon = stop.geometry.coordinates[0];
                if (!isFinite(stopLat) || !isFinite(stopLon)) return;
                L.marker([stopLat, stopLon], { icon: createStopIcon(idx + 1, '#f59e0b') }).addTo(map).bindPopup(`<div class="stop-popup"><h3>🚏 ${escapeHtml(stop.name)}</h3><div class="popup-info"><span>📏 ${stop.distance}m de ti</span></div></div>`, { maxWidth: 260, className: 'custom-popup' });
            });
        } catch (error) { console.error('Error buscando paradas:', error); alert('Error al buscar paradas. ¿Estás conectado?'); }
        finally { if (gpsBtn) gpsBtn.classList.remove('searching'); }
    }, (error) => {
        if (gpsBtn) gpsBtn.classList.remove('searching');
        if (error.code === 1) alert('Permite el acceso al GPS en tu navegador.');
        else if (error.code === 2) alert('Ubicación no disponible. Verifica tu conexión.');
        else alert('Timeout al obtener ubicación.');
    }, { enableHighAccuracy: true, timeout: 15000, maximumAge: 60000 });
}

// ── Search ──
let searchIndex = [];

function buildSearchIndex(geojsonData) {
    searchIndex = [];
    geojsonData.features.forEach((feature, routeIndex) => {
        const routeId = feature.properties.id;
        const routeName = feature.properties.name;
        const color = CONFIG.routeColors[routeIndex % CONFIG.routeColors.length];
        const stops = feature.properties.stops || [];
        stops.forEach(stop => {
            searchIndex.push({ name: stop.name || `Parada ${stops.indexOf(stop)+1}`, lat: stop.lat, lon: stop.lon, routeId, routeName, routeColor: color });
        });
        searchIndex.push({ name: routeName, lat: null, lon: null, routeId, routeName, routeColor: color, isRoute: true });
    });
}

function initSearch() {
    const input = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');
    const resultsEl = document.getElementById('search-results');
    if (!input || !clearBtn || !resultsEl) return;

    input.addEventListener('input', () => {
        const query = input.value.trim().toLowerCase();
        if (query.length < 2) { resultsEl.classList.remove('show'); clearBtn.style.display = 'none'; return; }
        clearBtn.style.display = 'block';
        const matches = searchIndex.filter(item => item.name.toLowerCase().includes(query)).slice(0, 8);
        if (matches.length === 0) {
            resultsEl.innerHTML = '<div class="search-result-item" style="cursor:default"><span style="color:var(--text-muted);font-size:13px">Sin resultados</span></div>';
        } else {
            resultsEl.innerHTML = matches.map(item => {
                const icon = item.isRoute ? '🛣️' : '🚏';
                const sub = item.isRoute ? 'Ruta de bus' : escapeHtml(item.routeName);
                return `<div class="search-result-item" data-lat="${item.lat}" data-lon="${item.lon}" data-routeid="${item.routeId}" data-isroute="${item.isRoute || false}">
                    <span class="result-icon">${icon}</span>
                    <div class="result-info">
                        <span class="result-name">${escapeHtml(item.name)}</span>
                        <span class="result-sub"><span class="chip-dot" style="background:${item.routeColor}"></span>${sub}</span>
                    </div>
                </div>`;
            }).join('');
        }
        resultsEl.classList.add('show');
    });

    resultsEl.addEventListener('click', (e) => {
        const item = e.target.closest('.search-result-item');
        if (!item) return;
        const lat = parseFloat(item.dataset.lat), lon = parseFloat(item.dataset.lon);
        const routeId = parseInt(item.dataset.routeid), isRoute = item.dataset.isroute === 'true';
        if (isRoute || isNaN(lat)) {
            showRouteDetail(routeId);
            centerOnRoute(routeId);
        } else {
            map.setView([lat, lon], 17, { animate: true, duration: 0.8 });
            showRouteDetail(routeId);
            addRecentStop({ name: item.querySelector('.result-name').textContent, lat, lon, routeId });
        }
        input.value = ''; resultsEl.classList.remove('show'); clearBtn.style.display = 'none';
    });

    clearBtn.addEventListener('click', () => { input.value = ''; resultsEl.classList.remove('show'); clearBtn.style.display = 'none'; input.focus(); });
    document.addEventListener('click', (e) => { if (!e.target.closest('#search-bar')) resultsEl.classList.remove('show'); });
}

// ── Chips de filtro (única vista de rutas) ──
function populateRouteFilter(geojsonData) {
    const chipsEl = document.getElementById('route-filter-chips');
    if (!chipsEl) return;
    chipsEl.innerHTML = '<span class="filter-chip active" data-routeid="all">🌐 Todo</span>';

    geojsonData.features.forEach((feature, index) => {
        const routeId = feature.properties.id;
        const routeName = feature.properties.name;
        const color = CONFIG.routeColors[index % CONFIG.routeColors.length];
        const shortName = routeName.length > 14 ? routeName.substring(0, 13) + '…' : routeName;
        const chip = document.createElement('span');
        chip.className = 'filter-chip';
        chip.dataset.routeid = routeId;
        chip.innerHTML = `<span class="chip-dot" style="background:${color}"></span>${escapeHtml(shortName)}`;
        chip.addEventListener('click', () => toggleRouteFilter(routeId, chip));
        chipsEl.appendChild(chip);
    });

    chipsEl.querySelector('[data-routeid="all"]').addEventListener('click', showRouteOverview);
}

function toggleRouteFilter(routeId, chipElement) {
    if (activeFilterRouteId === routeId) {
        showRouteOverview();
    } else {
        activeFilterRouteId = routeId;
        showRouteDetail(routeId);
    }
}

// ── Dark Mode ──
function initDarkMode() {
    const toggle = document.getElementById('dark-mode-toggle');
    if (!toggle) return;
    const saved = localStorage.getItem('optibus-dark-mode');
    if (saved === 'true' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
        document.body.classList.add('dark');
        toggle.textContent = '☀️';
    }
    toggle.addEventListener('click', () => {
        const isDark = document.body.classList.toggle('dark');
        toggle.textContent = isDark ? '☀️' : '🌙';
        localStorage.setItem('optibus-dark-mode', isDark.toString());
    });
}

// ── Favoritos ──
const RECENT_STOPS_KEY = 'optibus-recent-stops';
const FAV_STOPS_KEY = 'optibus-fav-stops';
const MAX_RECENT = 5;

function addRecentStop(stop) {
    let recent = [];
    try { recent = JSON.parse(localStorage.getItem(RECENT_STOPS_KEY) || '[]'); } catch(e) {}
    recent = recent.filter(s => !(s.lat === stop.lat && s.lon === stop.lon));
    recent.unshift(stop);
    if (recent.length > MAX_RECENT) recent = recent.slice(0, MAX_RECENT);
    localStorage.setItem(RECENT_STOPS_KEY, JSON.stringify(recent));
    renderFavoritesList();
}

function toggleFavoriteStop(stop) {
    let favs = [];
    try { favs = JSON.parse(localStorage.getItem(FAV_STOPS_KEY) || '[]'); } catch(e) {}
    const idx = favs.findIndex(s => s.lat === stop.lat && s.lon === stop.lon);
    if (idx >= 0) favs.splice(idx, 1); else favs.unshift(stop);
    localStorage.setItem(FAV_STOPS_KEY, JSON.stringify(favs));
    renderFavoritesList();
}

function getFavorites() {
    try { return JSON.parse(localStorage.getItem(FAV_STOPS_KEY) || '[]'); } catch(e) { return []; }
}

function renderFavoritesList() {
    const favSection = document.getElementById('favorites-section');
    const favList = document.getElementById('favorites-list');
    if (!favSection || !favList) return;
    const favs = getFavorites();
    const recents = [];
    try { recents = JSON.parse(localStorage.getItem(RECENT_STOPS_KEY) || '[]'); } catch(e) {}
    const allItems = [...favs.map(f => ({...f, isFav: true})), ...recents.filter(r => !favs.some(f => f.lat === r.lat && f.lon === r.lon)).map(r => ({...r, isFav: false}))];
    if (allItems.length === 0) { favSection.classList.remove('has-favorites'); return; }
    favSection.classList.add('has-favorites');
    favList.innerHTML = allItems.slice(0, 6).map(item => {
        const favIcon = item.isFav ? '⭐' : '🕐';
        return `<div class="stop-list-item" data-lat="${item.lat}" data-lon="${item.lon}" data-routeid="${item.routeId}">
            <span class="stop-list-number" style="background:var(--primary)">${favIcon}</span>
            <span class="stop-list-name">${escapeHtml(item.name)}</span>
            <button class="btn-icon" title="${item.isFav ? 'Quitar de favoritos' : 'Agregar a favoritos'}" style="font-size:12px;width:24px;height:24px"
                onclick="event.stopPropagation();toggleFavoriteStop({name:'${escapeHtml(item.name).replace(/'/g, "\\'")}',lat:${item.lat},lon:${item.lon},routeId:${item.routeId}});return false;">${item.isFav ? '★' : '☆'}</button>
        </div>`;
    }).join('');
    favList.querySelectorAll('.stop-list-item').forEach(el => {
        el.addEventListener('click', () => {
            const lat = parseFloat(el.dataset.lat), lon = parseFloat(el.dataset.lon), routeId = parseInt(el.dataset.routeid);
            map.setView([lat, lon], 17, { animate: true, duration: 0.8 });
            if (routeId) showRouteDetail(routeId);
        });
    });
}

// ── Init ──
document.addEventListener('DOMContentLoaded', () => {
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js').then(reg => console.log('✅ SW registrado')).catch(err => console.error('❌ SW:', err));
        });
    }
    loadRoutes();
    connectWebSocket();

    document.getElementById('btn-gps')?.addEventListener('click', findNearbyStops);
    document.getElementById('btn-refresh')?.addEventListener('click', async () => {
        if (wsInstance && wsInstance.readyState === WebSocket.OPEN) wsInstance.close(1000, 'Refresh');
        if ('serviceWorker' in navigator) { try { const regs = await navigator.serviceWorker.getRegistrations(); await Promise.all(regs.map(r => r.unregister())); } catch(e) {} }
        if ('caches' in window) { try { const names = await caches.keys(); await Promise.all(names.map(n => caches.delete(n))); } catch(e) {} }
        setTimeout(() => window.location.reload(), 300);
    });
    document.getElementById('btn-toggle-panel')?.addEventListener('click', () => {
        document.getElementById('side-panel')?.classList.toggle('collapsed');
    });

    initSearch();
    initDarkMode();
});