// ======================================================================
// OptiBus-PWA — Módulo de Internacionalización (i18n)
// Uso: importar en index.html después de app.js
// Cambiar idioma: i18n.setLang('en') o i18n.setLang('es')
// ======================================================================

const i18n = (() => {
    const LANGUAGES = {
        es: {
            panelTitle: 'OptiBus',
            searchPlaceholder: 'Buscar parada o ruta…',
            loading: 'Cargando rutas…',
            noRoutes: 'Sin rutas configuradas',
            selectRoute: 'Selecciona una ruta para ver sus paradas',
            noStops: 'Sin paradas registradas',
            paradas: 'Paradas',
            route: 'Ruta de bus',
            noResults: 'Sin resultados',
            connected: 'Conectado',
            disconnected: 'Sin conexión',
            gpsHere: 'Estás aquí',
            noNearbyStops: 'No hay paradas cercanas a tu ubicación (radio: 300 metros).',
            gpsError: 'Permite el acceso al GPS en tu navegador.',
            gpsUnavailable: 'Ubicación no disponible. Verifica tu conexión.',
            gpsTimeout: 'Timeout al obtener ubicación.',
            darkMode: 'Modo oscuro',
            todo: 'Todo',
            favorites: 'Favoritos',
            recent: 'Reciente',
            addFav: 'Agregar a favoritos',
            removeFav: 'Quitar de favoritos',
            centerRoute: 'Centrar en ruta',
            zoomRoute: 'Zoom a ruta',
            togglePanel: 'Mostrar / Ocultar panel',
            reload: 'Recargar App y limpiar Caché',
            findNearby: 'Encontrar mi parada cercana',
            meters: 'm de ti',
        },
        en: {
            panelTitle: 'OptiBus',
            searchPlaceholder: 'Search stop or route…',
            loading: 'Loading routes…',
            noRoutes: 'No routes configured',
            selectRoute: 'Select a route to see its stops',
            noStops: 'No stops registered',
            paradas: 'Stops',
            route: 'Bus route',
            noResults: 'No results',
            connected: 'Connected',
            disconnected: 'Disconnected',
            gpsHere: 'You are here',
            noNearbyStops: 'No stops near your location (300m radius).',
            gpsError: 'Allow GPS access in your browser.',
            gpsUnavailable: 'Location unavailable. Check your connection.',
            gpsTimeout: 'Timeout getting location.',
            darkMode: 'Dark mode',
            todo: 'All',
            favorites: 'Favorites',
            recent: 'Recent',
            addFav: 'Add to favorites',
            removeFav: 'Remove from favorites',
            centerRoute: 'Center on route',
            zoomRoute: 'Zoom to route',
            togglePanel: 'Show / Hide panel',
            reload: 'Reload App and clear Cache',
            findNearby: 'Find nearby stop',
            meters: 'm away',
        }
    };

    let currentLang = localStorage.getItem('optibus-lang') || 
                      (navigator.language?.startsWith('es') ? 'es' : 'en') || 'es';

    function setLang(lang) {
        if (LANGUAGES[lang]) {
            currentLang = lang;
            localStorage.setItem('optibus-lang', lang);
        }
    }

    function t(key) {
        return LANGUAGES[currentLang]?.[key] || LANGUAGES['es'][key] || key;
    }

    return { t, setLang, getLang: () => currentLang };
})();