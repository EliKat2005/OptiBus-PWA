// Coordenadas iniciales (Centro de Ibarra)
const IBARRA_LAT = 0.3517;
const IBARRA_LON = -78.1223;

const API_URL = '';
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${wsProtocol}//${window.location.host}/ws`;

// 1. Inicializar mapa de Leaflet
const map = L.map('map').setView([IBARRA_LAT, IBARRA_LON], 14);

// 2. Cargar capa base (OpenStreetMap)
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap - OptiBus MVP'
}).addTo(map);

// Objeto para control de marcadores
const busMarkers = {};
const MAX_BUS_MARKERS = 50; // Límite de seguridad para prevenir DoS

// Referencia al indicador de conexión
const connectionStatusEl = document.getElementById('connection-status');
const connectionTextEl = document.getElementById('connection-text');

function updateConnectionStatus(connected) {
    if (!connectionStatusEl || !connectionTextEl) return;
    if (connected) {
        connectionStatusEl.className = 'connected';
        connectionTextEl.textContent = '🟢 Conectado';
    } else {
        connectionStatusEl.className = 'connection-lost';
        connectionTextEl.textContent = '🔴 Sin conexión';
    }
    // Ocultar automáticamente tras 3 segundos si está conectado
    if (connected) {
        setTimeout(() => {
            connectionStatusEl.style.opacity = '0';
        }, 3000);
        connectionStatusEl.style.opacity = '1';
    }
}

// 3. Cargar rutas
async function loadRoutes() {
    try {
        const response = await fetch(`${API_URL}/api/routes`);
        if (!response.ok) {
            throw new Error(`Error HTTP: ${response.status}`);
        }
        const geojsonData = await response.json();
        
        const routeLayer = L.geoJSON(geojsonData, {
            style: function (feature) {
                return { color: "#2563eb", weight: 5, opacity: 0.8 };
            }
        }).addTo(map);
        
        if (geojsonData.features && geojsonData.features.length > 0) {
            map.fitBounds(routeLayer.getBounds());
        }
    } catch (error) {
        console.error("Error al cargar rutas estáticas:", error);
    }
}

// 4. WebSocket con reconexión exponencial
let wsReconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;
let wsInstance = null;

function connectWebSocket() {
    // Cerrar instancia anterior si existe
    if (wsInstance && wsInstance.readyState !== WebSocket.CLOSED) {
        wsInstance.close();
    }
    
    const ws = new WebSocket(WS_URL);
    wsInstance = ws;

    ws.onopen = () => {
        console.log("🟢 WebSocket conectado");
        updateConnectionStatus(true);
        wsReconnectDelay = 1000; // Resetear backoff
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            if (data.type === "bus_positions" && Array.isArray(data.buses)) {
                data.buses.forEach(bus => {
                    // DevSecOps: Validar coordenadas antes de usar
                    if (typeof bus.lat !== 'number' || typeof bus.lon !== 'number' ||
                        bus.lat < -90 || bus.lat > 90 || bus.lon < -180 || bus.lon > 180) {
                        console.warn('Coordenadas inválidas recibidas:', bus);
                        return;
                    }
                    
                    if (busMarkers[bus.id]) {
                        busMarkers[bus.id].setLatLng([bus.lat, bus.lon]);
                    } else {
                        // Limitar número de marcadores para prevenir DoS
                        if (Object.keys(busMarkers).length >= MAX_BUS_MARKERS) {
                            console.warn('Límite de marcadores alcanzado');
                            return;
                        }
                        const marker = L.marker([bus.lat, bus.lon]).addTo(map);
                        const sourceLabel = bus.source === 'real' ? '📡 Real' : '';
                        marker.bindPopup(`<b>🚌 Unidad:</b> ${escapeHtml(bus.id)}<br>${escapeHtml(sourceLabel)}`);
                        busMarkers[bus.id] = marker;
                    }
                });
            }
        } catch (err) {
            console.error('Error procesando mensaje WS:', err);
        }
    };

    ws.onclose = (event) => {
        console.log(`🔴 WebSocket desconectado (código ${event.code}). Reconectando en ${wsReconnectDelay/1000}s...`);
        updateConnectionStatus(false);
        
        // Backoff exponencial con cota máxima
        setTimeout(connectWebSocket, wsReconnectDelay);
        wsReconnectDelay = Math.min(wsReconnectDelay * 2, MAX_RECONNECT_DELAY);
    };

    ws.onerror = (error) => {
        console.error('Error en WebSocket:', error);
        // El onclose se disparará después, no hacemos nada extra aquí
    };
}

// DevSecOps: Escapar HTML para prevenir XSS en popups
function escapeHtml(str) {
    const div = document.createElement('div');
    div.appendChild(document.createTextNode(str));
    return div.innerHTML;
}

// Inicializar al cargar el DOM
document.addEventListener('DOMContentLoaded', () => {
    loadRoutes();
    connectWebSocket();
    
    // Configurar botón GPS
    const gpsBtn = document.getElementById('btn-gps');
    if (gpsBtn) {
        gpsBtn.addEventListener('click', findNearbyStops);
    }
});

// 5. Función de búsqueda de paradas cercanas
async function findNearbyStops() {
    if (!navigator.geolocation) {
        alert("Tu navegador no soporta geolocalización");
        return;
    }

    const gpsBtn = document.getElementById('btn-gps');
    if (gpsBtn) gpsBtn.classList.add('searching');

    navigator.geolocation.getCurrentPosition(async (position) => {
        const userLat = position.coords.latitude;
        const userLon = position.coords.longitude;
        
        // DevSecOps: Validar coordenadas del GPS
        if (!isFinite(userLat) || !isFinite(userLon) || 
            userLat < -90 || userLat > 90 || userLon < -180 || userLon > 180) {
            alert("Coordenadas GPS inválidas recibidas de tu dispositivo.");
            if (gpsBtn) gpsBtn.classList.remove('searching');
            return;
        }
        
        map.setView([userLat, userLon], 16);
        
        L.marker([userLat, userLon], {
            icon: L.icon({
                iconUrl: 'https://cdn-icons-png.flaticon.com/512/149/149059.png',
                iconSize: [30, 30]
            })
        }).addTo(map).bindPopup("<b>¡Estás aquí!</b>").openPopup();

        try {
            // Codificar parámetros para prevenir inyección
            const params = new URLSearchParams({
                lat: userLat.toString(),
                lon: userLon.toString(),
                radius_meters: '700'
            });
            const response = await fetch(`${API_URL}/api/stops/nearby?${params}`);
            
            if (!response.ok) {
                throw new Error(`Error HTTP: ${response.status}`);
            }
            
            const data = await response.json();
            
            if(!data.nearby_stops || data.nearby_stops.length === 0) {
                alert("No hay paradas a menos de 700 metros de tu ubicación.");
                return;
            }

            data.nearby_stops.forEach(stop => {
                if (!stop.geometry || !Array.isArray(stop.geometry.coordinates)) {
                    console.warn('Datos de parada inválidos:', stop);
                    return;
                }
                const stopLat = stop.geometry.coordinates[1];
                const stopLon = stop.geometry.coordinates[0];
                
                if (!isFinite(stopLat) || !isFinite(stopLon)) return;
                
                L.circleMarker([stopLat, stopLon], {
                    radius: 8,
                    fillColor: "#10b981",
                    color: "#047857",
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.8
                }).addTo(map).bindPopup(`<b>🚏 ${escapeHtml(stop.name)}</b><br> A ${stop.distance} metros de ti.`);
            });
        } catch(error) {
            console.error("Error obteniendo paradas:", error);
            alert("Error al buscar paradas. ¿Estás conectado a internet?");
        } finally {
            if (gpsBtn) gpsBtn.classList.remove('searching');
        }
        
    }, (error) => {
        if (gpsBtn) gpsBtn.classList.remove('searching');
        if (error.code === 1) {
            alert("Por favor, permite el acceso al GPS desde los ajustes de tu navegador.");
        } else if (error.code === 2) {
            alert("No se pudo obtener tu ubicación. Verifica tu conexión.");
        } else {
            alert("Tu dispositivo tardó demasiado en obtener la ubicación.");
        }
    }, {
        enableHighAccuracy: true,
        timeout: 15000,
        maximumAge: 60000
    });
}