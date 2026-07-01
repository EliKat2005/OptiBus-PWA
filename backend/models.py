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


class Cooperative(Base):
    """Cooperativa de transporte — unidad de tenancy SaaS."""
    __tablename__ = "cooperatives"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    slug = Column(String(50), unique=True, nullable=False, index=True)
    api_key_hash = Column(String(255), nullable=False)
    max_buses = Column(Integer, default=10)
    is_active = Column(Boolean, default=True, index=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    routes = relationship("Route", back_populates="cooperative", cascade="all, delete-orphan")
    drivers = relationship("Driver", back_populates="cooperative", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_cooperatives_active', 'is_active'),
    )


class ApiKey(Base):
    """API Keys con roles, expiry y auditoría (DevSecOps)."""
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, index=True)
    key_hash = Column(String(255), nullable=False, index=True)
    role = Column(String(20), default="admin", index=True)
    scopes = Column(String(500), default="")
    expires_at = Column(DateTime(timezone=True), nullable=True)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    is_active = Column(Boolean, default=True, index=True)

    __table_args__ = (
        Index('idx_api_keys_active', 'is_active', 'expires_at'),
    )


class Driver(Base):
    """Conductores y administradores con autenticación JWT (multi-tenant)."""
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    cooperative_id = Column(Integer, ForeignKey("cooperatives.id"), nullable=False, index=True)
    email = Column(String(255), unique=True, index=True, nullable=False)
    password_hash = Column(String(255), nullable=True)
    name = Column(String(100), nullable=False)
    bus_id = Column(String(50), nullable=False, default="Bus-1")
    company = Column(String(100), nullable=True)
    role = Column(String(20), default="driver", index=True)
    reset_token = Column(String(128), nullable=True)
    reset_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    deleted_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))

    cooperative = relationship("Cooperative", back_populates="drivers")

    __table_args__ = (
        Index('idx_drivers_cooperative', 'cooperative_id', 'is_active'),
    )


class Route(Base):
    """Rutas de transporte (multi-tenant)."""
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    cooperative_id = Column(Integer, ForeignKey("cooperatives.id"), nullable=False, index=True)
    name = Column(String, index=True, nullable=False)
    geom = Column(Geometry(geometry_type='LINESTRING', srid=4326), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC))
    updated_at = Column(DateTime(timezone=True), onupdate=lambda: datetime.now(UTC))

    cooperative = relationship("Cooperative", back_populates="routes")
    stops = relationship("Stop", back_populates="route", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_routes_geom_gist', 'geom', postgresql_using='gist'),
        Index('idx_routes_cooperative', 'cooperative_id'),
    )


class Stop(Base):
    """Paradas de transporte (multi-tenant)."""
    __tablename__ = "stops"

    id = Column(Integer, primary_key=True, index=True)
    cooperative_id = Column(Integer, ForeignKey("cooperatives.id"), nullable=False, index=True)
    route_id = Column(Integer, ForeignKey("routes.id"), index=True, nullable=True)
    name = Column(String, index=True, nullable=False)
    geom = Column(Geometry(geometry_type='POINT', srid=4326), nullable=False)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)

    route = relationship("Route", back_populates="stops")

    __table_args__ = (
        Index('idx_stops_geom_gist', 'geom', postgresql_using='gist'),
        Index('idx_stops_route_id', 'route_id'),
        Index('idx_stops_cooperative', 'cooperative_id'),
    )


class BusPosition(Base):
    """Historial de posiciones GPS de los buses (multi-tenant)."""
    __tablename__ = "bus_positions"

    id = Column(Integer, primary_key=True, index=True)
    cooperative_id = Column(Integer, ForeignKey("cooperatives.id"), nullable=False, index=True)
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
        Index('idx_bus_positions_cooperative', 'cooperative_id', 'recorded_at'),
        CheckConstraint('speed >= 0', name='ck_speed_non_negative'),
    )


class GeofenceAlert(Base):
    """Alertas de geocerca (desvíos de ruta, entradas/salidas de zonas)."""
    __tablename__ = "geofence_alerts"

    id = Column(Integer, primary_key=True, index=True)
    cooperative_id = Column(Integer, ForeignKey("cooperatives.id"), nullable=False, index=True)
    bus_id = Column(String, index=True, nullable=False)
    route_id = Column(Integer, nullable=True)
    alert_type = Column(String(50), nullable=False)  # 'off_route', 'on_route', 'zone_entry', 'zone_exit'
    message = Column(String(500), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        Index('idx_geofence_coop_time', 'cooperative_id', 'created_at'),
    )


class Infraction(Base):
    """Infracciones: excesos de velocidad, desvíos de ruta."""
    __tablename__ = "infractions"

    id = Column(Integer, primary_key=True, index=True)
    cooperative_id = Column(Integer, ForeignKey("cooperatives.id"), nullable=False, index=True)
    bus_id = Column(String, index=True, nullable=False)
    driver_id = Column(Integer, nullable=True)
    infraction_type = Column(String(50), nullable=False)  # 'speeding', 'off_route'
    speed_kmh = Column(Float, default=0.0)
    max_allowed_kmh = Column(Float, default=60.0)
    lat = Column(Float, nullable=True)
    lon = Column(Float, nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(UTC), index=True)

    __table_args__ = (
        Index('idx_infractions_coop_time', 'cooperative_id', 'recorded_at'),
        CheckConstraint('speed_kmh >= 0', name='ck_infraction_speed_non_negative'),
    )
