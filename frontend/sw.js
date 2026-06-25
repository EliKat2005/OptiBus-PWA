// OptiBus Service Worker - Estrategia Cache First solo para assets propios
// CORRECCIÓN: Versionado estático (sin Date.now()) para evitar regeneración infinita
const CACHE_VERSION = 'v2.1.0';
const CACHE_NAME = `optibus-pwa-${CACHE_VERSION}`;
const ASSETS_TO_CACHE = [
  '/',
  '/index.html',
  '/app.js',
  '/style.css',
  '/sw.js',
  '/manifest.json',
  '/icons/icon-192.png',
  '/icons/icon-512.png'
];

// Dominios externos que NUNCA deben cachearse (tiles, CDNs, etc.)
const EXTERNAL_DOMAINS = [
  'unpkg.com',
  'tile.openstreetmap.org',
  'cdn-icons-png.flaticon.com',
  'cdn.iconscout.com'
];

function isExternalRequest(url) {
  return EXTERNAL_DOMAINS.some(domain => url.hostname.includes(domain));
}

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
  self.skipWaiting();
});

// Evento de activación: limpiar caches viejos
self.addEventListener('activate', (event) => {
  console.log('[SW] Activando Service Worker...');
  event.waitUntil(
    caches.keys().then((cacheNames) => {
      const cachesToDelete = cacheNames.filter(name => 
        name.startsWith('optibus-pwa-') && name !== CACHE_NAME
      );
      return Promise.all(
        cachesToDelete.map(cacheName => {
          console.log(`[SW] Eliminando cache viejo: ${cacheName}`);
          return caches.delete(cacheName);
        })
      );
    })
  );
  self.clients.claim();
});

// CORRECCIÓN: Interceptar fetch con estrategia selectiva:
// - Assets propios: Cache First con Network fallback
// - API: Network First con Cache fallback  
// - Tiles/CDN externos: SOLO Network (sin cachear, sin interceptar errores)
self.addEventListener('fetch', (event) => {
  const url = new URL(event.request.url);
  
  // No interceptar WebSockets
  if (url.protocol === 'ws:' || url.protocol === 'wss:') {
    return;
  }
  
  // CORRECCIÓN: Recursos externos (tiles, CDN) -> pasar directo, no cachear
  if (isExternalRequest(url)) {
    // No interceptamos: el navegador maneja la petición normalmente
    return;
  }
  
  // Para peticiones a la API: Network First, Cache como fallback
  if (url.pathname.startsWith('/api/')) {
    event.respondWith(networkFirstWithCache(event.request));
    return;
  }

  // Admin dashboard: NUNCA cachear (contiene datos dinámicos)
  if (url.pathname === '/admin') {
    // Pasar directo, sin cachear
    return;
  }
  
  // Para assets propios y navegación: Cache First, Network fallback
  event.respondWith(cacheFirstWithNetworkFallback(event.request));
});

// Estrategia Network First: intentar red, SIEMPRE refrescar cache si OK
async function networkFirstWithCache(request) {
  try {
    const networkResponse = await fetch(request.clone());
    if (networkResponse && networkResponse.ok) {
      // Reemplazar cache con la respuesta fresca
      const cache = await caches.open(CACHE_NAME);
      await cache.put(request, networkResponse.clone());
      return networkResponse;
    }
    // Si la red responde con error (4xx/5xx), buscar en cache
    const cached = await caches.match(request);
    if (cached) {
      console.log('[SW] Red devolvió error, usando cache:', request.url);
      return cached;
    }
    // Sin cache y con error de red → devolver el error original
    return networkResponse;
  } catch (error) {
    console.log('[SW] Sin red, buscando en cache:', request.url);
    const cached = await caches.match(request);
    if (cached) return cached;
    return new Response(JSON.stringify({ error: 'offline' }), {
      status: 503,
      headers: { 'Content-Type': 'application/json' }
    });
  }
}

// CORRECCIÓN: Cache First para assets propios EXCLUSIVAMENTE.
// Si no está en caché y falla la red, devolver respuesta vacía en lugar de lanzar error
async function cacheFirstWithNetworkFallback(request) {
  const cached = await caches.match(request);
  if (cached) {
    // Revalidar en segundo plano
    fetch(request).then(response => {
      if (response && response.ok) {
        caches.open(CACHE_NAME).then(cache => {
          cache.put(request, response);
        });
      }
    }).catch(() => {});
    return cached;
  }
  
  try {
    const networkResponse = await fetch(request);
    if (networkResponse && networkResponse.ok) {
      const cache = await caches.open(CACHE_NAME);
      cache.put(request, networkResponse.clone());
    }
    return networkResponse;
  } catch (error) {
    // Si es navegación HTML, devolver página offline
    if (request.mode === 'navigate') {
      return new Response(
        '<html><body style="font-family:sans-serif;text-align:center;padding-top:20vh;"><h1>🚌 Sin conexión</h1><p>OptiBus necesita internet para funcionar.</p><p>Recarga cuando tengas señal.</p></body></html>',
        { headers: { 'Content-Type': 'text/html' } }
      );
    }
    // CORRECCIÓN: Devolver respuesta vacía en vez de lanzar error
    // Esto evita que Leaflet y otros componentes fallen catastróficamente
    return new Response('', { status: 200, headers: { 'Content-Type': 'text/plain' } });
  }
}
