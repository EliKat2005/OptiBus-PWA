# 📡 API Reference — OptiBus Backend

Base URL: `https://ecae.me`

## Autenticación

| Método | Header | Uso |
|--------|--------|-----|
| API Key | `Authorization: Bearer <key>` | Endpoints GPS, admin |
| JWT | `Authorization: Bearer <token>` | Conductores, refresh |
| Query Param | `?api_key=<key>` | Solo `/admin` |

## Endpoints Públicos

### `GET /health`
Estado del servidor.

```bash
curl https://ecae.me/health
# → {"status":"ok","database":"connected","redis":"connected","version":"0.4.0"}
```

### `GET /api/routes`
Todas las rutas con paradas (cache Redis 60s).

```bash
curl https://ecae.me/api/routes
# → {"type":"FeatureCollection","features":[...]}
```

### `GET /api/stops/nearby?lat=0.35&lon=-78.12&radius_meters=300`
Paradas cercanas a coordenadas.

### `GET /api/eta?bus_id=Bus-1&stop_id=5`
Tiempo estimado de llegada a una parada.

## Endpoints Protegidos (API Key o JWT)

### `POST /api/gps/update`
```bash
curl -H "Authorization: Bearer <key>" \
  -H "Content-Type: application/json" \
  -d '{"bus_id":"Bus-1","lat":0.35,"lon":-78.12,"speed":30.5}' \
  https://ecae.me/api/gps/update
```

### `GET /api/bus/active?minutes=5`
Buses activos recientemente.

### `GET /api/admin?api_key=<key>`
Dashboard HTML administrativo.

### `POST /api/routes/upload`
Subir ruta grabada desde APK (multipart GPX + JSON stops).

### `POST /api/stops/record`
Registrar parada individual en tiempo real.

### `POST /api/routes/plan`
```bash
curl -X POST https://ecae.me/api/routes/plan \
  -H "Content-Type: application/json" \
  -d '{"from_name":"Católica","to_name":"Estadio"}'
# → {"type":"direct","plan":[...],"message":"Toma la ruta..."}
```

## Auth Endpoints

| Endpoint | Método | Descripción |
|----------|--------|-------------|
| `/api/auth/login` | POST | Login email+password → JWT |
| `/api/auth/refresh` | POST | Refresh token |
| `/api/auth/register` | POST | Admin registra conductor |
| `/api/auth/forgot-password` | POST | Solicitar reset |
| `/api/auth/reset-password` | POST | Reset con token |
| `/api/auth/me` | GET | Perfil del usuario JWT |

## WebSocket

```
wss://ecae.me/ws
```

Mensajes entrantes: `{"type":"bus_positions","buses":[{"id":"Bus-1","lat":...,"lon":...}]}`
Mensajes salientes: posiciones con bearing calculado, broadcast a todos los clientes.