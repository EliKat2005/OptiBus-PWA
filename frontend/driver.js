const API_URL = '';
const BUS_ID = "BUS-REAL-01";
let watchId = null;
let isTransmitting = false;
let wakeLock = null;
let lastSendTime = 0; // Para no saturar el servidor

const btnToggle = document.getElementById('btn-toggle');
const statusText = document.getElementById('status-text');
const logDiv = document.getElementById('log');

function log(msg) {
    const p = document.createElement('div');
    p.textContent = `[${new Date().toLocaleTimeString()}] ${msg}`;
    logDiv.prepend(p);
}

btnToggle.addEventListener('click', () => {
    if (isTransmitting) {
        stopTransmission();
    } else {
        startTransmission();
    }
});

async function startTransmission() {
    if (!navigator.geolocation) {
        alert("Geolocalización no soportada en este dispositivo.");
        return;
    }

    // Solicitar WakeLock para evitar que la pantalla se apague y el navegador duerma la pestaña
    try {
        if ('wakeLock' in navigator) {
            wakeLock = await navigator.wakeLock.request('screen');
            wakeLock.addEventListener('release', () => {
                console.log('Pantalla desbloqueada (Wake Lock liberado)');
            });
            log("Wake Lock activado (Pantalla encendida).");
        }
    } catch (err) {
        log(`No se pudo bloquear la pantalla: ${err.name}, ${err.message}`);
    }

    // Pedir permisos y observar posición con alta precisión
    watchId = navigator.geolocation.watchPosition(
        sendPositionPayload,
        (error) => {
            log(`Error GPS: ${error.message}`);
            stopTransmission();
        },
        {
            enableHighAccuracy: true,
            maximumAge: 0,
            timeout: 5000
        }
    );

    isTransmitting = true;
    btnToggle.textContent = "Detener Transmisión";
    btnToggle.classList.add("stop");
    statusText.textContent = "EN RUTA (TRANSMITIENDO)";
    statusText.classList.add("active");
    log("GPS Watch API Iniciado...");
}

function stopTransmission() {
    if (watchId !== null) {
        navigator.geolocation.clearWatch(watchId);
        watchId = null;
    }
    
    if (wakeLock !== null) {
        wakeLock.release()
            .then(() => { wakeLock = null; });
    }

    isTransmitting = false;
    btnToggle.textContent = "Iniciar Transmisión";
    btnToggle.classList.remove("stop");
    statusText.textContent = "OFFLINE";
    statusText.classList.remove("active");
    log("Transmisión detenida.");
}

async function sendPositionPayload(position) {
    const lat = position.coords.latitude;
    const lon = position.coords.longitude;
    
    // Evitar saturar Cloudflare/Backend: Solo enviar si han pasado más de 3 segundos
    const now = Date.now();
    if (now - lastSendTime < 3000) {
        return; 
    }
    lastSendTime = now;

    log(`Coordenadas: ${lat.toFixed(5)}, ${lon.toFixed(5)}`);

    const payload = {
        bus_id: BUS_ID,
        lat: lat,
        lon: lon
    };

    try {
        const response = await fetch(`${API_URL}/api/gps/update`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(payload)
        });

        if (response.ok) {
            console.log("Posición enviada al cerebro");
        } else {
            log(`Error del API: ${response.status}`);
        }
    } catch (error) {
        log(`Error red: ${error.message}`);
    }
}
