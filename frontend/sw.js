// OptiBus Service Worker - Estrategia Cache First con Network Fallback
// DevSecOps: Cache versionado automáticamente con timestamp
const CACHE_VERSION = 'v1.1.' + Date.now();
const CACHE_NAME = `optibus-pwa-${CACHE_VERSION}`;
const ASSETS_TO_CACHE = [
  '/',
  '/index.html',
  '/app.js',
  '/style.css',
  '/manifest.json',
  '/icons/icon-192.png'
];

// Evento de instalación: precachear assets estáticos con manejo de errores individual
self.addEventListener('install', (event) => {
  console.log(`[SW] Instalando Service Worker ${CACHE_VERSION}...`);
  event.waitUntil(
    caches.open(CACHE_NAME).then((cache) => {
      console.log('[SW] Precacheando assets esenciales');
      return Promise.allSettled(
        ASSETS_TO_CACHE.map(url =>
          cache.add(url).catch(err => {
            console.warn(`[SW] No se pudo precachear ${url}:`, err);
          })
        )
      );
    })
  );
  // Activar inmediatamente sin esperar a que se cierren pestañas viejas
  self.skipWaiting();
});

// Evento de activación: limpiar caches viejos (hasta 3 versiones anteriores)
self.addEventListener('activate', (event) => {
  console.log('[SW] Activando Service Worker...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      // Mantener solo el cache actual y los 2 anteriores
      const validCaches = cacheNames
        .filter(name => name.startsWith('optibus-pwa-'))
        .sort()
        .reverse();
      
      const cachesToDelete = validCaches.slice(3); // Eliminar más allá de 3 versiones
      
      return Promise.all(
        cachesToDelete.map(cacheName => {
          console.log(`[SW] Eliminando cache viejo: ${cacheName}`);
          return caches.delete(cacheName);
        })
      );
    })
  );
  // Tomar control inmediato de todos los clientes
  self.clients.claim();
});

// Estrategia: Stale-While-Revalidate para la API (datos frescos cuando sea posible)
// Cache First para assets estáticos
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  
  // No interceptar WebSockets
  if (url.protocol === 'ws:' || url.protocol === 'wss:') {
    return;
  }
  
  // Para peticiones a la API: Network First, Cache como fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirstWithCache(event.request));
    return;
  }
  
  // Para assets estáticos y navegación: Cache First, Network fallback
  event.respondWith(cacheFirstWithNetwork(event.request));
});

// Estrategia Network First: intentar red, si falla usar cache
async function networkFirstWithCache(request) {
  try {
    const networkResponse = await fetch(request);
    // Cachear la respuesta fresca para uso offline futuro
    if (networkResponse.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    console.log('[SW] Sin red, buscando en cache:', request.url);
    const cached = await caches.match(request);
    if (cached) return cached;
    // Último recurso: devolver JSON de error
    return new Response(JSON.stringify({ error: 'offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// Estrategia Cache First: intentar cache, si no existe ir a red
async function cacheFirstWithNetwork(request) {
  const cached = await caches.match(request);
  if (cached) {
    // Actualizar en segundo plano (stale-while-revalidate)
    fetch(request).then(response => {
      if (response.ok) {
        caches.open(CACHE_NAME).then(cache => {
          cache.put(request, response);
        });
      }
    }).catch(() => {});
    return cached;
  }
  
  try {
    const networkResponse = await fetch(request);
    if (networkResponse.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    // Para navegación HTML, devolver página offline
    if (request.mode === 'navigate') {
      return new Response(
        '<html><body style="font-family:sans-serif;text-align:center;padding-top:20vh;"><h1>🚌 Sin conexión</h1><p>OptiBus necesita internet para funcionar.</p><p>Recarga cuando tengas señal.</p></body></html>',
        { headers: { 'Content-Type': 'text/html' } }
      );
    }
    throw error;
  }
}