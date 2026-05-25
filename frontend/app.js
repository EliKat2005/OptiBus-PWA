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
        const geojsonData = await response.json();
        
        const routeLayer = L.geoJSON(geojsonData, {
            style: function (feature) {
                return { color: "#2563eb", weight: 5, opacity: 0.8 };
            }
        }).addTo(map);
        
        if (geojsonData.features.length > 0) {
            map.fitBounds(routeLayer.getBounds());
        }
    } catch (error) {
        console.error("Error al cargar rutas estáticas:", error);
    }
}

// 4. WebSocket con reconexión exponencial
let wsReconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;

function connectWebSocket() {
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log("🟢 WebSocket conectado");
        updateConnectionStatus(true);
        wsReconnectDelay = 1000; // Resetear backoff
    };

    ws.onmessage = (event) => {
        try {
            const data = JSON.parse(event.data);
            
            if (data.type === "bus_positions") {
                data.buses.forEach(bus => {
                    if (busMarkers[bus.id]) {
                        busMarkers[bus.id].setLatLng([bus.lat, bus.lon]);
                    } else {
                        const marker = L.marker([bus.lat, bus.lon]).addTo(map);
                        const sourceLabel = bus.source === 'real' ? '📡 Real' : '';
                        marker.bindPopup(`<b>🚌 Unidad:</b> ${bus.id}<br>${sourceLabel}`);
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
        
        map.setView([userLat, userLon], 16);
        
        L.marker([userLat, userLon], {
            icon: L.icon({
                iconUrl: 'https://cdn-icons-png.flaticon.com/512/149/149059.png',
                iconSize: [30, 30]
            })
        }).addTo(map).bindPopup("<b>¡Estás aquí!</b>").openPopup();

        try {
            const response = await fetch(`${API_URL}/api/stops/nearby?lat=${userLat}&lon=${userLon}&radius_meters=700`);
            const data = await response.json();
            
            if(data.nearby_stops.length === 0) {
                alert("No hay paradas a menos de 700 metros de tu ubicación.");
                return;
            }

            data.nearby_stops.forEach(stop => {
                const stopLat = stop.geometry.coordinates[1];
                const stopLon = stop.geometry.coordinates[0];
                
                L.circleMarker([stopLat, stopLon], {
                    radius: 8,
                    fillColor: "#10b981",
                    color: "#047857",
                    weight: 2,
                    opacity: 1,
                    fillOpacity: 0.8
                }).addTo(map).bindPopup(`<b>🚏 ${stop.name}</b><br> A ${stop.distance} metros de ti.`);
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