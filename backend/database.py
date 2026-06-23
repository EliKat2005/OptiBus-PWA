import os
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker, declarative_base

# Cargar .env solo si existe (desarrollo local), en producción las variables
# se inyectan desde compose.yaml
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# DevSecOps: Construir DATABASE_URL desde variables de entorno individuales
# sin hardcodear credenciales
POSTGRES_USER = os.getenv("POSTGRES_USER", "optibus")
POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD")
if not POSTGRES_PASSWORD:
    raise RuntimeError(
        "POSTGRES_PASSWORD es requerida. Define la variable de entorno o crea un archivo .env"
    )
POSTGRES_HOST = os.getenv("POSTGRES_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT", "5432")
POSTGRES_DB = os.getenv("POSTGRES_DB", "optibus")

# Aún aceptamos DATABASE_URL como variable de entorno por compatibilidad
DATABASE_URL = os.getenv(
    "DATABASE_URL",
    f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{POSTGRES_HOST}:{POSTGRES_PORT}/{POSTGRES_DB}"
)

# SQLAlchemy asíncrono requiere que especifiquemos el driver asyncpg
ASYNC_DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+asyncpg://") if DATABASE_URL.startswith("postgresql://") else DATABASE_URL

# Creamos el motor asíncrono con pool configurado
engine = create_async_engine(
    ASYNC_DATABASE_URL,
    echo=False,  # Deshabilitar echo en producción por seguridad y rendimiento
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # Verificar conexiones antes de usarlas
    pool_recycle=3600,   # Reciclar conexiones cada hora
)

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
