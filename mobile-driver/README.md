# OptiBus - Driver App (Android / Kotlin) 📱

Aplicación nativa para conductores diseñada bajo estándares open-source, apta para distribución en **F-Droid**.
A diferencia de la PWA, esta aplicación utiliza un `Foreground Service` en Android, lo que garantiza que la ubicación geográfica no se suspenda cuando la pantalla se apague.

## Enfoque Tecnológico

- **Lenguaje**: Kotlin 1.9+
- **Geolocalización**: `android.location.LocationManager` (Independiente de los Google Play Services para cumplir directivas de F-Droid).
- **Comunicación**: WebSockets (`OkHttp` o `Ktor`) apuntando al Backend de FastAPI.
- **Persistencia**: Foreground Service con notificación ineludible.

## DevSecOps: Build Containerizado 🐳

Para no ensuciar tu entorno local y asegurar compilaciones reproducibles e idénticas en cualquier pipeline CI/CD, hemos incluido un sistema de compilación en contenedor.

### Pasos para generar el `.apk` nativo usando Docker/Podman:

1. Ingresa a esta carpeta:
```bash
cd mobile-driver
```

2. (Solo la primera vez) Construye la imagen madre del compilador de Android:
```bash
docker build -t optibus-android-builder -f Dockerfile.build .
```

3. Ejecuta el compilador enviándole tu código fuente:
```bash
docker run --rm -v $(pwd):/workspace optibus-android-builder
```
> El `.apk` resultante se exportará automáticamente en `app/build/outputs/apk/release/` sin necesidad de instalar Android Studio.

## Próximos pasos de desarrollo

El siguiente paso es inicializar aquí un proyecto de Android (con `gradle init` o mediante Android Studio) e implementar las clases bases:
1. `MainActivity.kt`: Interfaz con botón para iniciar el rastreo.
2. `LocationForegroundService.kt`: Servicio en primer plano capturando lat/long e inyectándolos en la red WebSocket.
3. `AndroidManifest.xml`: Declarar permisos (`ACCESS_FINE_LOCATION`, `FOREGROUND_SERVICE_LOCATION`, `INTERNET`).
