# 🛠️ Desarrollo Local

## Setup del Backend

```bash
cd backend
python3 -m venv .venv
source .venv/bin/activate
uv pip install -r requirements.txt
uv pip install pytest pytest-asyncio httpx bandit ruff
```

## Ejecutar API localmente

```bash
cd backend
uvicorn main:app --reload --port 8000
# Health: http://localhost:8000/health
# Swagger: http://localhost:8000/docs
```

## Tests

```bash
cd backend
python -m pytest test_api.py -v
# 22 tests: health, auth, GPS, routes, stops, plan
```

## Lint y Formato

```bash
ruff check backend/          # Verificar errores
ruff check --fix backend/    # Auto-corregir
```

## Security Scan

```bash
bandit -r backend/ -x backend/test_api.py
```

## CI/CD (GitHub Actions)

Workflow: `.github/workflows/ci.yml`

| Job | Qué hace |
|-----|---------|
| Tests + Lint + Security | pytest + ruff + bandit |
| ShellCheck | Audita scripts bash |

Se ejecuta en Python 3.12 y 3.13.

## Variables de Entorno (.env)

```bash
cp .env.example .env
# Editar:
#   POSTGRES_PASSWORD (default: CHANGEME)
#   OPTIBUS_API_KEY (generar con: openssl rand -base64 32)
#   DOMAIN (localhost para desarrollo, dominio real para prod)
#   GRAFANA_PASSWORD (default: CHANGEME)