// Coordenadas iniciales (Centro de Ibarra)
const IBARRA_LAT = 0.3517;
const IBARRA_LON = -78.1223;

// Ahora usamos rutas relativas gracias a nuestro proxy reverso (Caddy)
const API_URL = '';
// Determinamos dinámicamente si es ws:// o wss:// basándonos en la URL actual
const wsProtocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
const WS_URL = `${wsProtocol}//${window.location.host}/ws`;

// 1. Inicializar mapa de Leaflet
const map = L.map('map').setView([IBARRA_LAT, IBARRA_LON], 14);

// 2. Cargar capa base (OpenStreetMap)
L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '© OpenStreetMap - OptiBus MVP'
}).addTo(map);

// Objeto para llevar el control de los iconos de los buses en el mapa
const busMarkers = {};

// 3. Función HTTP (REST) para cargar y dibujar las rutas desde PostGIS
async function loadRoutes() {
    try {
        const response = await fetch(`${API_URL}/api/routes`);
        const geojsonData = await response.json();
        
        const routeLayer = L.geoJSON(geojsonData, {
            style: function (feature) {
                return { color: "#2563eb", weight: 5, opacity: 0.8 };
            }
        }).addTo(map);
        
        // Auto-centrar el mapa basándose en la caja delimitadora de la ruta trazada
        if (geojsonData.features.length > 0) {
            map.fitBounds(routeLayer.getBounds());
        }
    } catch (error) {
        console.error("Error al cargar rutas estáticas:", error);
    }
}

// 4. Función en Tiempo Real (WebSockets) para mover los marcadores
function connectWebSocket() {
    const ws = new WebSocket(WS_URL);

    ws.onopen = () => {
        console.log("🟢 Conexión WebSocket establecida con el Cerebro OptiBus.");
    };

    ws.onmessage = (event) => {
        const data = JSON.parse(event.data);
        
        if (data.type === "bus_positions") {
            data.buses.forEach(bus => {
                // Si el autobús ya está en el mapa, animar a la nueva posición
                if (busMarkers[bus.id]) {
                    busMarkers[bus.id].setLatLng([bus.lat, bus.lon]);
                } else {
                    // Si es nuevo, creamos el marcador en el mapa
                    const marker = L.marker([bus.lat, bus.lon]).addTo(map);
                    marker.bindPopup(`<b>🚌 Unidad:</b> ${bus.id}`);
                    busMarkers[bus.id] = marker;
                }
            });
        }
    };

    ws.onclose = () => {
        console.log("🔴 WebSocket desconectado. Intentando reconectar en 3 segundos...");
        setTimeout(connectWebSocket, 3000);
    };
}

// Inicializar ciclo de vida de la aplicación frontend
document.addEventListener('DOMContentLoaded', () => {
    loadRoutes();
    connectWebSocket();
    
    // Configurar botón GPS
    document.getElementById('btn-gps').addEventListener('click', findNearbyStops);
});

// 5. Función de Geofence y UX
async function findNearbyStops() {
    if (!navigator.geolocation) {
        alert("Tu navegador no soporta geolocalización");
        return;
    }

    navigator.geolocation.getCurrentPosition(async (position) => {
        const userLat = position.coords.latitude;
        const userLon = position.coords.longitude;
        
        // Centrar mapa en el usuario
        map.setView([userLat, userLon], 16);
        
        // Colocar icono del usuario
        L.marker([userLat, userLon], {
            icon: L.icon({
                iconUrl: 'https://cdn-icons-png.flaticon.com/512/149/149059.png',
                iconSize: [30, 30]
            })
        }).addTo(map).bindPopup("<b>¡Estás aquí!</b>").openPopup();

        // Llamada al backend para preguntar al PostGIS por el radio de 500m
        try {
            const response = await fetch(`${API_URL}/api/stops/nearby?lat=${userLat}&lon=${userLon}&radius_meters=700`);
            const data = await response.json();
            
            if(data.nearby_stops.length === 0) {
                alert("No hay paradas a menos de 700 metros de tu ubicación.");
                return;
            }

            // Pintar paradas cercanas de verde
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
        }
        
    }, (error) => {
        alert("Por favor, permite el acceso al GPS para buscar tus paradas.");
    });
}