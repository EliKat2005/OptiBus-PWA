"""
OSRM Snapping Router - OptiBus DevSecOps
Uses the OSRM map-matching API to gracefully snap noisy GPS coordinates
onto actual roadways, producing clean, professional LINESTRING tracks like Uber/InDrive.
"""

import logging
import os
from typing import List, Tuple, Optional
import httpx

logger = logging.getLogger("optibus-osrm")

OSRM_BASE_URL = os.getenv("OSRM_BASE_URL", "http://osrm:5000")


async def snap_to_roads(
    points: List[Tuple[float, float, str]],  # [(lat, lon, iso_time)]
    radius_meters: float = 25.0,
    gaps: str = "ignore",
) -> Optional[List[Tuple[float, float]]]:
    """
    Matches a noisy GPS trajectory to the actual road network using OSRM match API.

    Args:
        points: List of (lat, lon, iso_time) sorted by timestamp.
        radius_meters: Search radius for snapping. Default ~25m tolerates urban GPS noise.
        gaps: How to handle gaps. Options: "ignore" (default), "split".

    Returns:
        List of (lon, lat) snapped to roads, or None if OSRM is unavailable or fails.
        Returns coordinates in PostGIS-friendly order: (lon, lat).

    Example:
        snapped = await snap_to_roads(gps_points)
        if snapped:
            linestring = f"LINESTRING({', '.join(f'{lon} {lat}' for lon, lat in snapped)})"
    """
    if len(points) < 2:
        logger.warning("Snap requires at least 2 points. Returning without snapping.")
        return None

    # Build OSRM match request
    # Format: "lon,lat;lon,lat;..." with optional timestamps
    coordinates = ";".join(f"{lon},{lat}" for lat, lon, _ in points)

    # OSRM requires at least 2 coordinates and max ~100 per request
    if len(points) > 100:
        logger.info(f"Trimming {len(points)} points to 100 for OSRM (API limit).")
        step = len(points) // 100 + 1
        sampled = points[::step]
        coordinates = ";".join(f"{lon},{lat}" for lat, lon, _ in sampled)

    url = (
        f"{OSRM_BASE_URL}/match/v1/driving/"
        f"{coordinates}"
        f"?geometries=geojson&overview=full&radiuses={radius_meters}&gaps={gaps}"
    )

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.get(url)
            response.raise_for_status()
            data = response.json()

            if data.get("code") != "Ok" or not data.get("matchings"):
                logger.warning(f"OSRM match returned no results: {data.get('code', 'unknown')}")
                return None

            # Return first (best) matching
            geometry = data["matchings"][0]["geometry"]["coordinates"]
            # OSRM returns (lon, lat), same order as PostGIS expects
            logger.info(
                f"OSRM snapped: {len(points)} raw pts → {len(geometry)} road-matched pts"
            )
            return [(lon, lat) for lon, lat in geometry]

    except httpx.HTTPError as e:
        logger.warning(f"OSRM unavailable (HTTP error): {e}")
        return None
    except Exception as e:
        logger.error(f"OSRM snap failed: {type(e).__name__}: {e}")
        return None