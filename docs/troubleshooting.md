# 🚑 Troubleshooting — Errores Comunes

## 1. `rootlessport cannot expose privileged port 443`

**Causa**: Podman no tiene permiso para puertos < 1024.

```bash
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/99-rootless-ports.conf
podman-compose down && ./deploy.sh
```

## 2. `sd-bus call: Interactive authentication required`

**Causa**: `loginctl enable-linger` no se ejecutó o sesión no renovada.

```bash
sudo loginctl enable-linger $USER
# 🔴 CERRAR sesión SSH y volver a conectarse
```

## 3. PWA muestra "0 paradas" pero la BD tiene datos

**Causa**: Service Worker cachea versión vieja.

```
F12 → Application → Service Workers → Unregister
Application → Storage → Clear site data → Recargar
```

## 4. `net.ipv4.ip_unprivileged_port_start = 1024 (debe ser <= 80)`

**Causa**: Pre-flight check en `deploy.sh` falla.

```bash
sudo sysctl -w net.ipv4.ip_unprivileged_port_start=80
echo 'net.ipv4.ip_unprivileged_port_start=80' | sudo tee /etc/sysctl.d/99-rootless-ports.conf
```

## 5. GitHub Actions: Tests fallan con `AssertionError: plugin.py:558`

**Causa**: `pytest-asyncio` en modo STRICT sin `loop_scope`.

**Solución**: Archivo `backend/pytest.ini` con `asyncio_mode = auto`

## 6. Ruff: 101 errores de lint en CI

**Causa**: Código con espacios en blanco, imports sin usar.

```bash
cd backend && source .venv/bin/activate
ruff check --fix .
git add -A && git commit -m "fix(lint): Ruff auto-fix" && git push
```

## 7. APK: Paradas OK pero ruta NO se registra

**Causa**: GPS cleaner filtra demasiados puntos por velocidad (>80 km/h).

**Solución**: `backend/gps_cleaner.py` → `MAX_SPEED_KMH = 150`