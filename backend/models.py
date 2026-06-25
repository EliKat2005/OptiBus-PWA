from datetime import UTC, datetime

from database import Base
from geoalchemy2 import Geometry
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
)
from sqlalchemy.orm import relationship


class ApiKey(Base):
    """API Keys con roles, expiry y auditoría (DevSecOps)."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False, index=True)  # SHA-256 de la key
    role = Column(String(20), default="admin", index=True)  # "admin", "readonly", "gps"
    scopes = Column(String(500), default="")  # scope separados por coma: "gps,routes,admin"
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    is_active = Column(Boolean, default=True, index=True)

    __table_args__ = (
        Index('idx_api_keys_active', 'is_active', 'expires_at'),
    )

class Driver(Base):
    """Conductores y administradores con autenticación JWT."""
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    name = Column(String(100), nullable=False)
    bus_id = Column(String(50), nullable=False, default="Bus-1")
    company = Column(String(100), nullable=True)
    role = Column(String(20), default="driver", index=True)
    reset_token = Column(String(128), nullable=True)  # Ampliado a 128 para bcrypt/token_urlsafe
    reset_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)  # Soft-delete
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    geom = Column(Geometry(geometry_type='LINESTRING', srid=4326), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(UTC))

    stops = relationship("Stop", back_populates="route", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_routes_geom_gist', 'geom', postgresql_using='gist'),
    )

class Stop(Base):
    __tablename__ = "stops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"), index=True, nullable=True)
    geom = Column(Geometry(geometry_type='POINT', srid=4326), nullable=False)
    # DB7: Columnas desnormalizadas para evitar ST_Y/ST_X en consultas frecuentes
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    route = relationship("Route", back_populates="stops")

    __table_args__ = (
        Index('idx_stops_geom_gist', 'geom', postgresql_using='gist'),
        Index('idx_stops_route_id', 'route_id'),
    )

class BusPosition(Base):
    """Historial de posiciones GPS de los buses."""
    __tablename__ = "bus_positions"

    id = Column(Integer, primary_key=True, index=True)
    bus_id = Column(String, index=True, nullable=False)
    geom = Column(Geometry(geometry_type='POINT', srid=4326), nullable=False)
    speed = Column(Float, default=0.0)
    route_id = Column(Integer, nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        Index('idx_bus_positions_bus_time', 'bus_id', 'recorded_at'),
        Index('idx_bus_positions_geom_gist', 'geom', postgresql_using='gist'),
        Index('idx_bus_positions_route', 'route_id'),
        Index('idx_bus_positions_recorded', 'recorded_at'),
        CheckConstraint('speed >= 0', name='ck_speed_non_negative'),
    )
