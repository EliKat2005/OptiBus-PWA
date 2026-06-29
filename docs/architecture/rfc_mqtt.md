"""
OptiBus Security Middleware — DevSecOps v5.0
Rate limiting por endpoint, JWT blocklist, y hardening de la API.
"""

import hashlib
import logging
import time

from fastapi import Request
from rate_limiter import get_redis

logger = logging.getLogger("optibus-security")

# ── Rate Limits por endpoint (requests/minuto) ──
RATE_LIMITS = {
    "/api/routes": 30,
    "/api/stops/nearby": 20,
    "/api/stops/search": 30,
    "/api/gps/update": 120,
    "/api/routes/plan": 20,
    "/api/routes/upload": 10,
    "/admin": 10,
    "/api/auth/login": 10,
    "/api/auth/register": 5,
    "/health": 60,
    "default": 60,
}


async def rate_limit_by_path(request: Request, client_ip: str) -> bool:
    """
    Rate limiting específico por ruta del endpoint.
    Retorna True si la petición debe ser rechazada (HTTP 429).
    """
    path = request.url.path
    max_req = RATE_LIMITS.get("default", 60)
    for prefix, limit in RATE_LIMITS.items():
        if path.startswith(prefix) and limit < max_req:
            max_req = limit

    r = await get_redis()
    if r:
        key = f"rl:path:{client_ip}:{path}"
        window = 60
        current = await r.incr(key)
        if current == 1:
            await r.expire(key, window)
        if current > max_req:
            logger.warning(f"Rate limit ({path}): {client_ip} ({current}/{max_req})")
            return True
    return False


async def revoke_jwt(jti: str, ttl_seconds: int = 43200) -> bool:
    """
    Añade un JWT a la blocklist en Redis.
    TTL por defecto: 12 horas (43200 segundos).
    """
    r = await get_redis()
    if r:
        key = f"jwt:bl:{jti}"
        await r.setex(key, ttl_seconds, "1")
        logger.info(f"JWT revocado: {jti[:10]}... (TTL={ttl_seconds}s)")
        return True
    logger.warning("Redis no disponible para JWT blocklist")
    return False


async def is_jwt_revoked(jti: str) -> bool:
    """Verifica si un JWT está en la blocklist."""
    r = await get_redis()
    if r:
        return await r.exists(f"jwt:bl:{jti}") > 0
    return False


def generate_jti() -> str:
    """Genera un JWT ID único para revocación."""
    return hashlib.sha256(f"{time.time()}-{id(object())}".encode()).hexdigest()[:16]
</content>

<write_to_file>
<path>backend/utils/obfuscation.py</path>
<content>
"""
OptiBus ID Obfuscation — DevSecOps v5.0
Ofuscación de IDs autoincrementables con XOR + base62.
Evita que la competencia enumere recursos iterando del 1 al 1000.
"""

import hashlib
import os

_salt = os.getenv("OPTIBUS_API_KEY", "optibus-default-salt")
_salt_hash = hashlib.sha256(_salt.encode()).hexdigest()[:16]
_MIN_LENGTH = 8
_ALPHABET = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"
_BASE = len(_ALPHABET)


def encode_id(entity_id: int) -> str:
    """Codifica un ID entero a un hash opaco de 8+ caracteres."""
    n = entity_id ^ int(_salt_hash, 16)
    result = []
    while n > 0:
        result.append(_ALPHABET[n % _BASE])
        n //= _BASE
    while len(result) < _MIN_LENGTH:
        pad_idx = (entity_id * 7 + len(result)) % _BASE
        result.append(_ALPHABET[pad_idx])
    return "".join(reversed(result))


def decode_id(obfuscated: str) -> int:
    """Decodifica un hash opaco de vuelta al ID entero original."""
    n = 0
    for char in obfuscated:
        if char in _ALPHABET:
            n = n * _BASE + _ALPHABET.index(char)
    return n ^ int(_salt_hash, 16)
</content>

<write_to_file>
<path>docs/architecture/rfc_mqtt.md</path>
<content>
# RFC: Migración de Telemetría GPS a MQTT

**Versión**: 1.0  
**Fecha**: 2026-06-27  
**Autor**: Arquitecto DevSecOps — OptiBus  
**Estado**: Diseño (Pre-implementación)

---

## 1. Resumen Ejecutivo

Actualmente el APK Android y futuros dispositivos ESP32 envían telemetría GPS
vía HTTP REST (`POST /api/gps/update`). Cada petición HTTP implica:
- Handshake TCP + TLS
- Cabeceras HTTP (~500 bytes)
- Autenticación JWT en cada request
- Overhead de 300-500ms en redes móviles (3G/4G)

**MQTT** es un protocolo binario ligero diseñado para IoT. Reduce overhead a ~10
bytes por mensaje, permite comunicación bidireccional (comandos al bus), y
escala a miles de dispositivos con un solo broker.

## 2. Arquitectura Propuesta

```
┌─────────────────┐     MQTT (TLS:8883)      ┌──────────────────┐
│  ESP32 / APK    │ ─────────────────────────→│  Mosquitto Broker │
│  (GPS Tracker)  │ ←─────────────────────────│  (Podman)         │
└─────────────────┘     QoS 1                └────────┬─────────┘
                                                       │
                                              ┌────────▼─────────┐
                                              │  MQTT Bridge      │
                                              │  (Python asyncio) │
                                              │  → WebSocket      │
                                              │  → PostGIS        │
                                              │  → Redis Cache    │
                                              └──────────────────┘
```

## 3. Topics MQTT

| Topic | Dirección | QoS | Formato |
|-------|-----------|-----|--------|
| `optibus/{coop}/bus/{id}/location` | Device → Broker | 1 | `{lat,lon,speed,ts}` |
| `optibus/{coop}/bus/{id}/command` | Broker → Device | 2 | `{cmd,params}` |
| `optibus/{coop}/bus/{id}/status` | Device → Broker | 1 | `{battery,signal}` |

## 4. Seguridad

- **TLS 1.3** en puerto 8883
- **Autenticación por certificado** (no username/password)
- **ACL por cooperativa**: cada dispositivo solo accede a topics de su `coop_slug`
- **Rate limiting**: 60 mensajes/minuto por dispositivo

## 5. Integración con Stack Actual

El bridge MQTT (`backend/iot_service/mqtt_bridge.py`) se suscribe a topics y:
1. Publica en WebSocket existente (reutiliza `ConnectionManager`)
2. Persiste en `bus_positions` (PostGIS) cada 5 segundos
3. Actualiza Redis (`bus:{bus_id}:pos`) para consultas en tiempo real

## 6. Fases de Implementación

| Fase | Semana | Hito |
|------|--------|------|
| 1 | 1-2 | Desplegar Mosquitto en compose.yaml + TLS |
| 2 | 3-4 | Bridge MQTT → WebSocket + Redis |
| 3 | 5-6 | Migrar APK Android de HTTP a MQTT |
| 4 | 7-8 | Firmware ESP32 con soporte MQTT nativo |

## 7. Decisiones Pendientes

- ¿Mosquitto o EMQX? EMQX ofrece dashboard web y clustering; Mosquitto es más ligero.
- ¿QoS 2 para comandos? QoS 1 es suficiente para telemetría.
- ¿Persistencia de sesiones? Sí, para reconexión de dispositivos móviles.