from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Index, Boolean
from geoalchemy2 import Geometry
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime, timezone

class Driver(Base):
    """Conductores y administradores con autenticación JWT."""
    __tablename__ = "drivers"

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String(255), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=True)
    name = Column(String(100), nullable=False)
    bus_id = Column(String(50), nullable=False, default="Bus-1")
    company = Column(String(100), nullable=True)
    role = Column(String(20), default="driver", index=True)
    reset_token = Column(String(64), nullable=True)
    reset_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    geom = Column(Geometry(geometry_type='LINESTRING', srid=4326), nullable=False)

    stops = relationship("Stop", back_populates="route")

    __table_args__ = (
        Index('idx_routes_geom_gist', 'geom', postgresql_using='gist'),
    )

class Stop(Base):
    __tablename__ = "stops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"))
    geom = Column(Geometry(geometry_type='POINT', srid=4326), nullable=False)

    route = relationship("Route", back_populates="stops")

    __table_args__ = (
        Index('idx_stops_geom_gist', 'geom', postgresql_using='gist'),
    )

class BusPosition(Base):
    """Historial de posiciones GPS de los buses."""
    __tablename__ = "bus_positions"

    id = Column(Integer, primary_key=True, index=True)
    bus_id = Column(String, index=True, nullable=False)
    geom = Column(Geometry(geometry_type='POINT', srid=4326), nullable=False)
    speed = Column(Float, default=0.0)
    route_id = Column(Integer, nullable=True)
    recorded_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True)

    __table_args__ = (
        Index('idx_bus_positions_bus_time', 'bus_id', 'recorded_at'),
        Index('idx_bus_positions_geom_gist', 'geom', postgresql_using='gist'),
    )
