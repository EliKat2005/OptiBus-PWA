"""
OptiBus Database Configuration — DevSecOps v4.0
Conexión asyncpg + SQLAlchemy usando config centralizado.
"""

import logging

from config import ASYNC_DATABASE_URL
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import declarative_base, sessionmaker

logger = logging.getLogger("optibus-database")

# ── Motor asíncrono ──
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,  # Deshabilitar echo en producción por seguridad y rendimiento
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verificar conexiones antes de usarlas
    pool_recycle=3600,  # Reciclar conexiones cada hora
)

# ── Fábrica de sesiones ──
SessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)

Base = declarative_base()


# ── Dependencia para FastAPI ──
async def get_db():
    """Yield session para inyección de dependencias de FastAPI."""
    async with SessionLocal() as session:
        yield session
