// ======================================================================
// OptiBus-PWA v0.5.0 — Visualización Profesional de Rutas y Paradas
// DevSecOps: Coordenadas validadas, escape HTML, límites de marcadores
// ======================================================================

const CONFIG = {
    center: [-0.2188, -78.5124],  // Quito, Ecuador (centro país)
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
    arrowInterval: 8,  // Flechas direccionales cada N puntos
};

const API_URL = '';
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${wsProtocol}//${window.location.host}/ws`;

// ──────────────────────────────────────────────
// 1. MAPA BASE PROFESIONAL
// ──────────────────────────────────────────────
const map = L.map('map', {
    center: CONFIG.center,
    zoom: CONFIG.defaultZoom,
    zoomControl: true,
    attributionControl: true
});

// Capa base OpenStreetMap (confiable, sin dependencia de CDNs externos)
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors · OptiBus'
}).addTo(map);

// ──────────────────────────────────────────────
// 2. GRUPOS DE CAPAS (para toggle)
// ──────────────────────────────────────────────
const routeLayers = {};       // { route_id: L.layerGroup }
const stopMarkers = [];       // [{ marker, route_id }]
const busMarkers = {};        // { bus_id: L.marker }
const busTrails = {};         // { bus_id: L.polyline }
let activeRouteIndex = -1;    // Ruta seleccionada (para highlight)

// Panel lateral
const routeListEl = document.getElementById('routeList');
const stopListEl = document.getElementById('stopList');

// ──────────────────────────────────────────────
// 3. ICONOS PERSONALIZADOS
// ──────────────────────────────────────────────

// Ícono de parada numerada (DivIcon)
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

// Ícono de bus (SVG rotado según bearing)
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

// ──────────────────────────────────────────────
// 4. CARGA DE RUTAS (ESTILO PROFESIONAL)
// ──────────────────────────────────────────────
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
    routeListEl.innerHTML = '';
    stopListEl.innerHTML = '';

    if (!geojsonData.features || geojsonData.features.length === 0) {
        routeListEl.innerHTML = '<div class="empty-state">🚏 Sin rutas configuradas</div>';
        return;
    }

    let allBounds = null;

    geojsonData.features.forEach((feature, routeIndex) => {
        const routeId = feature.properties.id;
        const routeName = feature.properties.name;
        const color = CONFIG.routeColors[routeIndex % CONFIG.routeColors.length];
        const coords = feature.geometry.coordinates;

        if (!coords || coords.length < 2) return;

        // Grupo de capa para esta ruta
        const layerGroup = L.layerGroup().addTo(map);
        routeLayers[routeId] = layerGroup;

        // ── Línea exterior (glow / sombra) ──
        const glowLine = L.polyline(
            coords.map(c => [c[1], c[0]]),
            {
                color: color,
                weight: CONFIG.routeWeight + 4,
                opacity: 0.15,
                smoothFactor: 2,
                interactive: false
            }
        ).addTo(layerGroup);

        // ── Línea principal ──
        const mainLine = L.polyline(
            coords.map(c => [c[1], c[0]]),
            {
                color: color,
                weight: CONFIG.routeWeight,
                opacity: CONFIG.routeOpacity,
                smoothFactor: 2,
                dashArray: null,
                lineCap: 'round',
                lineJoin: 'round'
            }
        ).addTo(layerGroup);

        // ── Flechas direccionales ──
        for (let i = CONFIG.arrowInterval; i < coords.length - 1; i += CONFIG.arrowInterval) {
            const p1 = coords[i];
            const p2 = coords[i + 1];
            const midLat = (p1[0] + p2[0]) / 2;
            const midLon = (p1[1] + p2[1]) / 2;
            const angle = Math.atan2(p2[0] - p1[0], p2[1] - p1[1]) * 180 / Math.PI + 90;
            
            L.marker([midLat, midLon], {
                icon: L.divIcon({
                    className: 'route-arrow-icon',
                    html: `<div class="route-arrow" style="--color: ${color}; transform: rotate(${angle}deg)">▶</div>`,
                    iconSize: [16, 16],
                    iconAnchor: [8, 8]
                }),
                interactive: false
            }).addTo(layerGroup);
        }

        // ── Tooltip al hover ──
        mainLine.bindTooltip(`<strong>${escapeHtml(routeName)}</strong><br><small>${coords.length} puntos</small>`, {
            sticky: true,
            direction: 'top',
            className: 'route-tooltip'
        });

        // ── Bounds ──
        const routeBounds = mainLine.getBounds();
        if (!allBounds) allBounds = routeBounds;
        else allBounds.extend(routeBounds);

        // ── Panel lateral: entrada de ruta ──
        const routeItem = document.createElement('div');
        routeItem.className = 'route-list-item';
        routeItem.innerHTML = `
            <div class="route-color-dot" style="background:${color}"></div>
            <div class="route-info">
                <strong>${escapeHtml(routeName)}</strong>
                <small>${coords.length} pts · Paradas: <span id="stopCount_${routeId}">-</span></small>
            </div>
            <div class="route-actions">
                <button class="btn-icon" title="Centrar en ruta" onclick="centerOnRoute(${routeId})">◎</button>
                <button class="btn-icon" title="Zoom a ruta" onclick="zoomToRoute(${routeId})">🔍</button>
            </div>
        `;
        routeItem.addEventListener('click', () => highlightRoute(routeId));
        routeListEl.appendChild(routeItem);

        // ── Renderizar paradas incluidas en la respuesta ──
        const stops = feature.properties.stops || [];
        const countEl = document.getElementById(`stopCount_${routeId}`);
        if (countEl) countEl.textContent = stops.length;

        stops.forEach((stop, index) => {
            const stopLat = stop.lat;
            const stopLon = stop.lon;
            const stopName = stop.name || `Parada ${index + 1}`;
            
            const marker = L.marker([stopLat, stopLon], {
                icon: createStopIcon(index + 1, color)
            });

            marker.bindPopup(`
                <div class="stop-popup">
                    <h3>🚏 ${escapeHtml(stopName)}</h3>
                    <div class="popup-info">
                        <span>📍 ${stopLat.toFixed(6)}, ${stopLon.toFixed(6)}</span>
                    </div>
                </div>
            `, { maxWidth: 260, className: 'custom-popup' });

            marker.bindTooltip(`<strong>${escapeHtml(stopName)}</strong>`, {
                direction: 'top',
                offset: [0, -18],
                className: 'stop-tooltip'
            });

            if (routeLayers[routeId]) {
                marker.addTo(routeLayers[routeId]);
            }
            stopMarkers.push({ marker, routeId, name: stopName, coords: [stopLat, stopLon] });
        });

        // Panel lateral: lista de paradas
        if (stops.length > 0) {
            const stopHeader = document.createElement('div');
            stopHeader.className = 'stop-list-header';
            stopHeader.innerHTML = `<span style="color:${color}">●</span> ${escapeHtml(routeName)}`;
            stopListEl.appendChild(stopHeader);
            
            stops.forEach((stop, idx) => {
                const stopItem = document.createElement('div');
                stopItem.className = 'stop-list-item';
                stopItem.innerHTML = `
                    <span class="stop-list-number" style="background:${color}">${idx + 1}</span>
                    <span class="stop-list-name">${escapeHtml(stop.name || `Parada ${idx + 1}`)}</span>
                `;
                stopItem.addEventListener('click', () => {
                    map.setView([stop.lat, stop.lon], 17, { animate: true });
                });
                stopListEl.appendChild(stopItem);
            });
        }
    });

    // Centrar en todas las rutas
    if (allBounds) {
        map.fitBounds(allBounds, { padding: [50, 50], maxZoom: 16 });
    }

    // ── Poblar search index, chips de filtro y favoritos ──
    buildSearchIndex(geojsonData);
    populateRouteFilter(geojsonData);
    renderFavoritesList();
}

// ──────────────────────────────────────────────
// 6. INTERACCIÓN: HIGHLIGHT DE RUTA
// ──────────────────────────────────────────────
function highlightRoute(routeId) {
    if (activeRouteIndex === routeId) {
        // Deseleccionar
        activeRouteIndex = -1;
        Object.values(routeLayers).forEach(lg => lg.setStyle({ opacity: CONFIG.routeOpacity }));
        Object.keys(routeLayers).forEach(id => {
            routeLayers[id].eachLayer(l => {
                if (l instanceof L.Polyline && l.options.color) {
                    l.setStyle({ weight: CONFIG.routeWeight });
                }
            });
        });
        document.querySelectorAll('.route-list-item').forEach(el => el.classList.remove('active'));
        return;
    }

    activeRouteIndex = routeId;

    // Atenuar otras rutas
    Object.entries(routeLayers).forEach(([id, lg]) => {
        if (parseInt(id) === routeId) {
            lg.setStyle({ opacity: 1 });
            lg.eachLayer(l => {
                if (l instanceof L.Polyline && l.options.color) {
                    l.setStyle({ weight: CONFIG.routeWeight + 2 });
                }
            });
        } else {
            lg.setStyle({ opacity: 0.2 });
            lg.eachLayer(l => {
                if (l instanceof L.Polyline && l.options.color) {
                    l.setStyle({ weight: 2 });
                }
            });
        }
    });

    // Highlight en panel
    document.querySelectorAll('.route-list-item').forEach((el, i) => {
        el.classList.toggle('active', i === Object.keys(routeLayers).indexOf(routeId));
    });
}

function centerOnRoute(routeId) {
    const lg = routeLayers[routeId];
    if (lg) {
        const bounds = L.latLngBounds();
        lg.eachLayer(l => {
            if (l instanceof L.Polyline) {
                l.getLatLngs().forEach(ll => bounds.extend(ll));
            }
        });
        map.fitBounds(bounds, { padding: [80, 80], maxZoom: 16 });
    }
}

function zoomToRoute(routeId) {
    const lg = routeLayers[routeId];
    if (lg) {
        const bounds = L.latLngBounds();
        lg.eachLayer(l => {
            if (l instanceof L.Polyline) {
                l.getLatLngs().forEach(ll => bounds.extend(ll));
            }
        });
        map.flyToBounds(bounds, { padding: [50, 50], maxZoom: 17, duration: 1.2 });
    }
}

// ──────────────────────────────────────────────
// 7. CONEXIÓN WEBSOCKET (con animación de buses)
// ──────────────────────────────────────────────
let wsReconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;
let wsInstance = null;
let pingTimer = null;
let wsConnectionAttempts = 0;
const busLastPos = {};  // { bus_id: { lat, lon, timestamp } }

function connectWebSocket() {
    if (wsInstance && wsInstance.readyState !== WebSocket.CLOSED) wsInstance.close();
    if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }

    const ws = new WebSocket(WS_URL);
    wsInstance = ws;
    wsConnectionAttempts++;

    ws.onopen = () => {
        updateConnectionStatus(true);
        wsReconnectDelay = 1000;
        wsConnectionAttempts = 0;
        
        pingTimer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
                ws.send(JSON.stringify({ type: "ping" }));
            }
        }, 30000);
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            if (data.type === "bus_positions" && Array.isArray(data.buses)) {
                data.buses.forEach(bus => {
                    // Validar coordenadas
                    if (typeof bus.lat !== 'number' || typeof bus.lon !== 'number' ||
                        bus.lat < -90 || bus.lat > 90 || bus.lon < -180 || bus.lon > 180) {
                        return;
                    }

                    // Calcular bearing si tenemos posición anterior
                    let bearing = 0;
                    const last = busLastPos[bus.id];
                    if (last && (bus.lat !== last.lat || bus.lon !== last.lon)) {
                        const dLon = (bus.lon - last.lon) * Math.PI / 180;
                        const y = Math.sin(dLon) * Math.cos(bus.lat * Math.PI / 180);
                        const x = Math.cos(last.lat * Math.PI / 180) * Math.sin(bus.lat * Math.PI / 180) -
                                  Math.sin(last.lat * Math.PI / 180) * Math.cos(bus.lat * Math.PI / 180) * Math.cos(dLon);
                        bearing = Math.atan2(y, x) * 180 / Math.PI;
                    }
                    busLastPos[bus.id] = { lat: bus.lat, lon: bus.lon, timestamp: Date.now() };

                    // Actualizar o crear marcador
                    if (busMarkers[bus.id]) {
                        busMarkers[bus.id].setLatLng([bus.lat, bus.lon]);
                        // Actualizar rotación del icono
                        const icon = createBusIcon(bearing);
                        busMarkers[bus.id].setIcon(icon);
                        
                        // Actualizar trail
                        if (busTrails[bus.id]) {
                            busTrails[bus.id].addLatLng([bus.lat, bus.lon]);
                            // Mantener solo últimos 20 puntos
                            const latlngs = busTrails[bus.id].getLatLngs();
                            if (latlngs.length > 20) {
                                busTrails[bus.id].setLatLngs(latlngs.slice(-20));
                            }
                        }
                    } else {
                        if (Object.keys(busMarkers).length >= CONFIG.maxBusMarkers) return;
                        
                        const marker = L.marker([bus.lat, bus.lon], {
                            icon: createBusIcon(0),
                            zIndexOffset: 1000
                        }).addTo(map);
                        
                        const sourceLabel = bus.source === 'real' ? '📡 GPS Real' : '🔄 Simulación';
                        marker.bindPopup(`
                            <div class="bus-popup">
                                <h3>🚌 ${escapeHtml(bus.id)}</h3>
                                <div class="popup-info">
                                    <span>📍 ${bus.lat.toFixed(6)}, ${bus.lon.toFixed(6)}</span>
                                    <span>🔗 ${escapeHtml(sourceLabel)}</span>
                                </div>
                            </div>
                        `, { maxWidth: 260, className: 'custom-popup' });
                        
                        busMarkers[bus.id] = marker;
                        
                        // Crear trail
                        const trail = L.polyline([[bus.lat, bus.lon]], {
                            color: '#2563eb',
                            weight: 2,
                            opacity: 0.4,
                            dashArray: '5 10',
                            interactive: false
                        }).addTo(map);
                        busTrails[bus.id] = trail;
                    }
                });

                // Limpiar buses inactivos (>60s sin actualizar)
                const now = Date.now();
                Object.entries(busLastPos).forEach(([id, pos]) => {
                    if (now - pos.timestamp > 60000) {
                        if (busMarkers[id]) {
                            map.removeLayer(busMarkers[id]);
                            delete busMarkers[id];
                        }
                        if (busTrails[id]) {
                            map.removeLayer(busTrails[id]);
                            delete busTrails[id];
                        }
                        delete busLastPos[id];
                    }
                });
            }
        } catch (err) {
            console.error('Error WS:', err);
        }
    };

    ws.onclose = (event) => {
        if (pingTimer) { clearInterval(pingTimer); pingTimer = null; }
        updateConnectionStatus(false);
        setTimeout(connectWebSocket, wsReconnectDelay);
        wsReconnectDelay = Math.min(wsReconnectDelay * 2, MAX_RECONNECT_DELAY);
    };
}

// ──────────────────────────────────────────────
// 8. INDICADOR DE CONEXIÓN
// ──────────────────────────────────────────────
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

// ──────────────────────────────────────────────
// 9. SERVICEWORKER + BOTÓN REFRESH
// ──────────────────────────────────────────────
function initServiceWorker() {
    if ('serviceWorker' in navigator) {
        window.addEventListener('load', () => {
            navigator.serviceWorker.register('/sw.js')
                .then(reg => console.log('✅ SW registrado:', reg.scope))
                .catch(err => console.error('❌ SW:', err));
        });
    }
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// ──────────────────────────────────────────────
// 10. BÚSQUEDA DE PARADAS CERCANAS (GPS)
// ──────────────────────────────────────────────
async function findNearbyStops() {
    if (!navigator.geolocation) {
        alert('Tu navegador no soporta geolocalización');
        return;
    }

    const gpsBtn = document.getElementById('btn-gps');
    if (gpsBtn) gpsBtn.classList.add('searching');

    navigator.geolocation.getCurrentPosition(async (position) => {
        const userLat = position.coords.latitude;
        const userLon = position.coords.longitude;

        if (!isFinite(userLat) || !isFinite(userLon) ||
            userLat < -90 || userLat > 90 || userLon < -180 || userLon > 180) {
            alert('Coordenadas GPS inválidas.');
            if (gpsBtn) gpsBtn.classList.remove('searching');
            return;
        }

        map.setView([userLat, userLon], 16, { animate: true });

        // Marcador de posición actual
        L.marker([userLat, userLon], {
            icon: L.divIcon({
                className: 'my-location-icon',
                html: '<div class="my-location-dot"></div>',
                iconSize: [20, 20],
                iconAnchor: [10, 10]
            })
        }).addTo(map).bindPopup('<b>📍 Estás aquí</b>').openPopup();

        try {
            const params = new URLSearchParams({
                lat: userLat.toString(),
                lon: userLon.toString(),
                radius_meters: '1000'
            });
            const response = await fetch(`${API_URL}/api/stops/nearby?${params}`);
            if (!response.ok) throw new Error(`HTTP ${response.status}`);

            const data = await response.json();
            if (!data.nearby_stops || data.nearby_stops.length === 0) {
                alert('No hay paradas a menos de 1 km.');
                return;
            }

            data.nearby_stops.forEach((stop, idx) => {
                if (!stop.geometry || !Array.isArray(stop.geometry.coordinates)) return;
                const stopLat = stop.geometry.coordinates[1];
                const stopLon = stop.geometry.coordinates[0];
                if (!isFinite(stopLat) || !isFinite(stopLon)) return;

                L.marker([stopLat, stopLon], {
                    icon: createStopIcon(idx + 1, '#f59e0b')
                }).addTo(map).bindPopup(`
                    <div class="stop-popup">
                        <h3>🚏 ${escapeHtml(stop.name)}</h3>
                        <div class="popup-info">
                            <span>📏 ${stop.distance}m de ti</span>
                        </div>
                    </div>
                `, { maxWidth: 260, className: 'custom-popup' });
            });
        } catch (error) {
            console.error('Error buscando paradas:', error);
            alert('Error al buscar paradas. ¿Estás conectado?');
        } finally {
            if (gpsBtn) gpsBtn.classList.remove('searching');
        }
    }, (error) => {
        if (gpsBtn) gpsBtn.classList.remove('searching');
        if (error.code === 1) alert('Permite el acceso al GPS en tu navegador.');
        else if (error.code === 2) alert('Ubicación no disponible. Verifica tu conexión.');
        else alert('Timeout al obtener ubicación.');
    }, {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 60000
    });
}

// ──────────────────────────────────────────────
// 11. INICIALIZACIÓN
// ──────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
    initServiceWorker();
    loadRoutes();
    connectWebSocket();

    // Botón GPS
    const gpsBtn = document.getElementById('btn-gps');
    if (gpsBtn) gpsBtn.addEventListener('click', findNearbyStops);

    // Botón Refresh
    const refreshBtn = document.getElementById('btn-refresh');
    if (refreshBtn) {
        refreshBtn.addEventListener('click', async () => {
            if (wsInstance && wsInstance.readyState === WebSocket.OPEN) {
                wsInstance.close(1000, 'Refresh');
            }
            if ('serviceWorker' in navigator) {
                try {
                    const regs = await navigator.serviceWorker.getRegistrations();
                    await Promise.all(regs.map(r => r.unregister()));
                } catch (e) {}
            }
            if ('caches' in window) {
                try {
                    const names = await caches.keys();
                    await Promise.all(names.map(n => caches.delete(n)));
                } catch (e) {}
            }
            setTimeout(() => window.location.reload(), 300);
        });
    }

    // Toggle panel lateral
    const toggleBtn = document.getElementById('btn-toggle-panel');
    if (toggleBtn) {
        toggleBtn.addEventListener('click', () => {
            const panel = document.getElementById('side-panel');
            if (panel) panel.classList.toggle('collapsed');
        });
    }

    // ── Inicializar Search, Filters, Dark Mode ──
    initSearch();
    initRouteFilter();
    initDarkMode();
    initFavorites();
});

// ======================================================================
// 12. SEARCH DE PARADAS (búsqueda en tiempo real con autocomplete)
// ======================================================================
let searchIndex = [];  // [{ name, lat, lon, routeId, routeName, routeColor }]

function buildSearchIndex(geojsonData) {
    searchIndex = [];
    geojsonData.features.forEach((feature, routeIndex) => {
        const routeId = feature.properties.id;
        const routeName = feature.properties.name;
        const color = CONFIG.routeColors[routeIndex % CONFIG.routeColors.length];
        const stops = feature.properties.stops || [];
        stops.forEach(stop => {
            searchIndex.push({
                name: stop.name || `Parada ${stops.indexOf(stop) + 1}`,
                lat: stop.lat,
                lon: stop.lon,
                routeId,
                routeName,
                routeColor: color
            });
        });
        // También indexar nombre de ruta
        searchIndex.push({
            name: routeName,
            lat: null,
            lon: null,
            routeId,
            routeName,
            routeColor: color,
            isRoute: true
        });
    });
}

function initSearch() {
    const input = document.getElementById('search-input');
    const clearBtn = document.getElementById('search-clear');
    const resultsEl = document.getElementById('search-results');

    if (!input || !clearBtn || !resultsEl) return;

    input.addEventListener('input', () => {
        const query = input.value.trim().toLowerCase();
        if (query.length < 2) {
            resultsEl.classList.remove('show');
            clearBtn.style.display = 'none';
            return;
        }
        clearBtn.style.display = 'block';

        const matches = searchIndex
            .filter(item => item.name.toLowerCase().includes(query))
            .slice(0, 8);  // máx 8 resultados

        if (matches.length === 0) {
            resultsEl.innerHTML = '<div class="search-result-item" style="cursor:default"><span style="color:var(--text-muted);font-size:13px">Sin resultados</span></div>';
        } else {
            resultsEl.innerHTML = matches.map(item => {
                const icon = item.isRoute ? '🛣️' : '🚏';
                const sub = item.isRoute
                    ? `Ruta con ${item.lat == null ? 'varias' : ''} paradas`
                    : `${item.routeName} • ${item.lat?.toFixed(6)}, ${item.lon?.toFixed(6)}`;
                return `
                    <div class="search-result-item" data-lat="${item.lat}" data-lon="${item.lon}" data-routeid="${item.routeId}" data-isroute="${item.isRoute || false}">
                        <span class="result-icon">${icon}</span>
                        <div class="result-info">
                            <span class="result-name">${escapeHtml(item.name)}</span>
                            <span class="result-sub">
                                <span class="chip-dot" style="background:${item.routeColor}"></span>
                                ${escapeHtml(sub)}
                            </span>
                        </div>
                    </div>`;
            }).join('');
        }
        resultsEl.classList.add('show');
    });

    // Click en resultado
    resultsEl.addEventListener('click', (e) => {
        const item = e.target.closest('.search-result-item');
        if (!item) return;
        const lat = parseFloat(item.dataset.lat);
        const lon = parseFloat(item.dataset.lon);
        const routeId = parseInt(item.dataset.routeid);
        const isRoute = item.dataset.isroute === 'true';

        if (isRoute || isNaN(lat)) {
            // Es una ruta → centrar en ella
            highlightRoute(routeId);
            centerOnRoute(routeId);
        } else {
            // Es una parada → volar a ella y destacar ruta
            map.setView([lat, lon], 17, { animate: true, duration: 0.8 });
            highlightRoute(routeId);
            // Guardar en favoritos recientes
            addRecentStop({ name: item.querySelector('.result-name').textContent, lat, lon, routeId });
        }

        input.value = '';
        resultsEl.classList.remove('show');
        clearBtn.style.display = 'none';
    });

    clearBtn.addEventListener('click', () => {
        input.value = '';
        resultsEl.classList.remove('show');
        clearBtn.style.display = 'none';
        input.focus();
    });

    // Cerrar dropdown al click fuera
    document.addEventListener('click', (e) => {
        if (!e.target.closest('#search-bar')) {
            resultsEl.classList.remove('show');
        }
    });
}

// ======================================================================
// 13. FILTRO DE RUTAS (chips de colores)
// ======================================================================
let activeFilterRouteId = null;

function initRouteFilter() {
    // Se pobla en renderRoutes()
}

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

    // Chip "Todo"
    chipsEl.querySelector('[data-routeid="all"]').addEventListener('click', () => {
        activeFilterRouteId = null;
        chipsEl.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
        chipsEl.querySelector('[data-routeid="all"]').classList.add('active');
        // Mostrar todas las rutas
        Object.values(routeLayers).forEach(lg => lg.setStyle({ opacity: CONFIG.routeOpacity }));
        Object.keys(routeLayers).forEach(id => {
            routeLayers[id].eachLayer(l => {
                if (l instanceof L.Polyline && l.options.color) {
                    l.setStyle({ weight: CONFIG.routeWeight });
                }
            });
        });
        map.fitBounds(getAllRoutesBounds(), { padding: [50, 50], maxZoom: 16 });
    });
}

function toggleRouteFilter(routeId, chipElement) {
    const chipsEl = document.getElementById('route-filter-chips');
    if (!chipsEl) return;

    if (activeFilterRouteId === routeId) {
        // Deseleccionar
        activeFilterRouteId = null;
        chipElement.classList.remove('active');
        chipsEl.querySelector('[data-routeid="all"]').classList.add('active');
        Object.values(routeLayers).forEach(lg => lg.setStyle({ opacity: CONFIG.routeOpacity }));
        Object.keys(routeLayers).forEach(id => {
            routeLayers[id].eachLayer(l => {
                if (l instanceof L.Polyline && l.options.color) {
                    l.setStyle({ weight: CONFIG.routeWeight });
                }
            });
        });
        map.fitBounds(getAllRoutesBounds(), { padding: [50, 50], maxZoom: 16 });
    } else {
        // Seleccionar esta ruta
        activeFilterRouteId = routeId;
        chipsEl.querySelectorAll('.filter-chip').forEach(c => c.classList.remove('active'));
        chipElement.classList.add('active');
        // Atenuar todas menos la seleccionada
        Object.entries(routeLayers).forEach(([id, lg]) => {
            if (parseInt(id) === routeId) {
                lg.setStyle({ opacity: 1 });
                lg.eachLayer(l => {
                    if (l instanceof L.Polyline && l.options.color) {
                        l.setStyle({ weight: CONFIG.routeWeight + 3 });
                    }
                });
            } else {
                lg.setStyle({ opacity: 0.08 });
                lg.eachLayer(l => {
                    if (l instanceof L.Polyline && l.options.color) {
                        l.setStyle({ weight: 1 });
                    }
                });
            }
        });
        centerOnRoute(routeId);
    }
}

function getAllRoutesBounds() {
    const bounds = L.latLngBounds();
    Object.values(routeLayers).forEach(lg => {
        lg.eachLayer(l => {
            if (l instanceof L.Polyline) {
                l.getLatLngs().forEach(ll => bounds.extend(ll));
            }
        });
    });
    return bounds;
}

// ======================================================================
// 14. DARK MODE
// ======================================================================
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

// ======================================================================
// 15. FAVORITOS (localStorage)
// ======================================================================
const RECENT_STOPS_KEY = 'optibus-recent-stops';
const FAV_STOPS_KEY = 'optibus-fav-stops';
const MAX_RECENT = 5;

function initFavorites() {
    // Placeholder — se llena dinámicamente en populateRouteFilter
    renderFavoritesList();
}

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
    if (idx >= 0) {
        favs.splice(idx, 1);
    } else {
        favs.unshift(stop);
    }
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

    if (allItems.length === 0) {
        favSection.classList.remove('has-favorites');
        return;
    }

    favSection.classList.add('has-favorites');
    favList.innerHTML = allItems.slice(0, 6).map(item => {
        const favIcon = item.isFav ? '⭐' : '🕐';
        return `
            <div class="stop-list-item" data-lat="${item.lat}" data-lon="${item.lon}" data-routeid="${item.routeId}">
                <span class="stop-list-number" style="background:var(--primary)">${favIcon}</span>
                <span class="stop-list-name">${escapeHtml(item.name)}</span>
                <button class="btn-icon" title="${item.isFav ? 'Quitar de favoritos' : 'Agregar a favoritos'}" 
                    style="font-size:12px;width:24px;height:24px"
                    onclick="event.stopPropagation();toggleFavoriteStop({name:'${escapeHtml(item.name).replace(/'/g, "\\'")}',lat:${item.lat},lon:${item.lon},routeId:${item.routeId}});return false;">
                    ${item.isFav ? '★' : '☆'}
                </button>
            </div>`;
    }).join('');

    // Click handlers
    favList.querySelectorAll('.stop-list-item').forEach(el => {
        el.addEventListener('click', () => {
            const lat = parseFloat(el.dataset.lat);
            const lon = parseFloat(el.dataset.lon);
            const routeId = parseInt(el.dataset.routeid);
            map.setView([lat, lon], 17, { animate: true, duration: 0.8 });
            if (routeId) highlightRoute(routeId);
        });
    });
}

