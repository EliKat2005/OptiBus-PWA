# OptiBus DevSecOps Makefile
# Comandos rápidos para desarrollo, testing y despliegue.

.PHONY: help install test test-gps lint format clean

help: ## Mostrar esta ayuda
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Instalar dependencias de desarrollo
	pip install -r backend/requirements.txt

test: ## Ejecutar tests de integración
	cd backend && POSTGRES_PASSWORD=testpass OPTIBUS_API_KEY=test-key-32-chars-minimum!! JWT_SECRET=test-jwt-secret-32-chars-minimum!! python -m pytest tests/ -v

test-gps: ## Ejecutar tests del GPS Cleaner
	cd backend && python -m pytest tests/ -v -k "gps" || echo "No hay tests específicos para GPS Cleaner aún"

lint: ## Linting con ruff
	ruff check backend/

format: ## Formatear con ruff
	ruff format backend/

clean: ## Limpiar archivos temporales
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete 2>/dev/null || true
	find . -type d -name "*.egg-info" -exec rm -rf {} + 2>/dev/null || true
	rm -rf .pytest_cache .ruff_cache .mypy_cache 2>/dev/null || true
	rm -rf .venv 2>/dev/null || true