"""Reject unsupported locations before looking up weather or flood data."""
import math

from fastapi import HTTPException
from floodsight.config import AOI_BBOX


def validate_location(lat: float, lon: float) -> None:
    if not (math.isfinite(lat) and math.isfinite(lon)
            and -90 <= lat <= 90 and -180 <= lon <= 180):
        raise HTTPException(422, "Coordinates must be finite WGS84 latitude/longitude.")
    west, south, east, north = AOI_BBOX
    if not (west <= lon <= east and south <= lat <= north):
        raise HTTPException(422, "Location is outside FloodSight's Lagos pilot coverage.")
