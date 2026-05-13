from fastapi import FastAPI
from contextlib import asynccontextmanager
from database import engine, Base
import models

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Al iniciar la aplicación, creamos las tablas en la BD (incluyendo columnas espaciales)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield

app = FastAPI(title="OptiBus MVP", version="0.1.0", lifespan=lifespan)

@app.get("/health")
async def health_check():
    return {"status": "ok", "service": "optibus-api"}