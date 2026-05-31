from sqlalchemy import Column, Integer, String, Float, ForeignKey, DateTime, Index
from geoalchemy2 import Geometry
from sqlalchemy.orm import relationship
from database import Base
from datetime import datetime, timezone

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
