# 📱 App Android — OptiBus Driver

## Requisitos

- Java 17 o superior
- Android SDK 35
- Podman (para compilar en contenedor)

## Compilación con Podman (recomendado)

```bash
cd mobile-driver
podman build -t optibus-android-builder -f Dockerfile.build .
podman run --rm -v "$(pwd)":/workspace optibus-android-builder
# APK generado en: app/build/outputs/apk/debug/app-debug.apk
```

## Configuración para Release (firmado)

```bash
cd mobile-driver
cp keystore.properties.template keystore.properties
nano keystore.properties
# Cambiar assembleDebug → assembleRelease en Dockerfile.build
```

## Arquitectura

| Componente | Descripción |
|-----------|-------------|
| `MainActivity.kt` | Interfaz de grabación: campos de ruta, API key, bus ID |
| `RouteRecorderService.kt` | Foreground Service: captura GPS, escribe GPX, sube al backend |
| `StringEscaper.kt` | Utilidad de escape para XML/JSON seguro |

## Endpoints usados por el APK

| Endpoint | Método | Uso |
|----------|--------|-----|
| `/api/routes/upload` | POST (multipart) | Subir ruta GPX + paradas JSON |
| `/api/stops/record` | POST (JSON) | Registrar parada individual en tiempo real |

## Permisos Android

```xml
ACCESS_FINE_LOCATION
ACCESS_COARSE_LOCATION
FOREGROUND_SERVICE
FOREGROUND_SERVICE_LOCATION
INTERNET
```

## Variables de BuildConfig

```kotlin
DEFAULT_SERVER_URL = "https://ecae.me"
```

## Solución de Problemas

- **"Servidor: 401"**: Verificar que `api_key` coincida con `OPTIBUS_API_KEY` en `.env`
- **Ruta no se registra**: Posible filtro agresivo del GPS cleaner. MAX_SPEED_KMH → 150