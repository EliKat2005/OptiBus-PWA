import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Leemos la variable del entorno, inyectada por el compose.yaml
DATABASE_URL = os.getenv("DATABASE_URL", "postgresql://optibus:optibus123@localhost:5432/optibus")

# SQLAlchemy asíncrono requiere que especifiquemos el driver asyncpg
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://")

# Creamos el motor asíncrono
engine = create_async_engine(ASYNC_DATABASE_URL, echo=True)

# Configuramos la fábrica de sesiones
SessionLocal = sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False
)

Base = declarative_base()

# Dependencia para FastAPI
async def get_db():
    async with SessionLocal() as session:
        yield session
