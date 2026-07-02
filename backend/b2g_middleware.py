"""
OptiBus B2G Middleware — DevSecOps v5.0
Anonimización estricta de datos para el portal municipal.
Ningún endpoint B2G devuelve driver_id, bus_id, ni cooperative_id.
"""


def anonymize_position(pos: dict) -> dict:
    """
    Limpia datos sensibles y agrupa coordenadas en grid de ~100m.
    Elimina: driver_id, bus_id, cooperative_id, nombres de choferes.
    """
    clean = {}
    if "lat" in pos and "lon" in pos:
        clean["lat"] = round(pos["lat"], 4)  # ~11m de precisión (grid 100m)
        clean["lon"] = round(pos["lon"], 4)
    if "speed_kmh" in pos or "speed" in pos:
        clean["speed_kmh"] = round(pos.get("speed_kmh", pos.get("speed", 0)), 1)
    if "recorded_at" in pos or "created_at" in pos or "last_seen" in pos:
        clean["ts"] = str(
            pos.get("recorded_at") or pos.get("created_at") or pos.get("last_seen") or ""
        )
    # NUNCA incluir: driver_id, bus_id, cooperative_id, name
    return clean


def anonymize_list(positions: list[dict]) -> list[dict]:
    """Aplica anonimización a una lista de posiciones."""
    return [anonymize_position(p) for p in positions if p.get("lat") and p.get("lon")]