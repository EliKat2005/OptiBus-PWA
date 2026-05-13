from sqlalchemy import Column, Integer, String, ForeignKey
from geoalchemy2 import Geometry
from sqlalchemy.orm import relationship
from database import Base

class Route(Base):
    __tablename__ = "routes"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    # Almacenamos la trayectoria de la ruta como un LineString.
    # SRID 4326 corresponde a WGS 84 (coordenadas GPS de latitud y longitud).
    geom = Column(Geometry(geometry_type='LINESTRING', srid=4326), nullable=False)

    stops = relationship("Stop", back_populates="route")

class Stop(Base):
    __tablename__ = "stops"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, index=True, nullable=False)
    route_id = Column(Integer, ForeignKey("routes.id"))
    # Almacenamos la ubicación exacta de la parada como un Point.
    geom = Column(Geometry(geometry_type='POINT', srid=4326), nullable=False)

    route = relationship("Route", back_populates="stops")
