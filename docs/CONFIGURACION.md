# Configuración de OptiBus

## Variables de Entorno

Crear un archivo `.env` en la raíz del proyecto copiando este template:

```env
# --- Base de Datos PostgreSQL/PostGIS ---
POSTGRES_DB=optibus
POSTGRES_USER=optibus
POSTGRES_PASSWORD=cambiame_por_una_contraseña_segura
POSTGRES_HOST=db
POSTGRES_PORT=5432

# --- API Backend ---
# CORS_ORIGINS: dominios permitidos separados por coma
CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080

# ENABLE_BUS_SIMULATOR: activar simulador de buses (solo desarrollo)
ENABLE_BUS_SIMULATOR=false

# API_RELOAD: activar recarga automática (solo desarrollo)
# Dejar vacío en producción
# API_RELOAD=--reload

# --- Servidor Web (Caddy) ---
# CADDY_PORT: puerto para interfaz web
CADDY_PORT=8080
```

## Seguridad

- **NUNCA** subir el archivo `.env` al repositorio
- Usar contraseñas fuertes y únicas para cada entorno
- En producción, habilitar HTTPS con Caddy (agregar `tls` al Caddyfile)
- Rotar credenciales periódicamente
