"""Local LGA gazetteer: no third-party autocomplete or resident-location sharing."""
from fastapi import APIRouter, Query
from api.coordinates import validate_location

router = APIRouter(prefix="/places", tags=["places"])
PLACES = [
    ("Agege", 6.622, 3.322), ("Ajeromi-Ifelodun", 6.464, 3.321),
    ("Alimosho", 6.580, 3.270), ("Amuwo-Odofin", 6.468, 3.293),
    ("Eti-Osa", 6.431, 3.505), ("Ifako-Ijaiye", 6.642, 3.312),
    ("Ikeja", 6.597, 3.340), ("Ikorodu", 6.619, 3.506),
    ("Kosofe", 6.582, 3.408), ("Lagos Island", 6.453, 3.394),
    ("Lagos Mainland", 6.518, 3.364), ("Mushin", 6.536, 3.350),
    ("Ojo", 6.464, 3.179), ("Oshodi-Isolo", 6.543, 3.354),
    ("Surulere", 6.497, 3.353),
]


@router.get("/search")
def search(q: str = Query(min_length=2, max_length=120)):
    query = q.casefold().strip()
    return [{"display_name": f"{name}, Lagos, Nigeria (area centre)",
             "lat": lat, "lon": lon} for name, lat, lon in PLACES
            if query in name.casefold()][:7]


@router.get("/reverse")
def reverse(lat: float, lon: float):
    validate_location(lat, lon)
    from api.data_provider import nearest_cell
    cell = nearest_cell(lat, lon)
    name = cell.get("lga_name")
    if not isinstance(name, str) or not name.strip():
        # A nearest LGA centre is a label suggestion, never a boundary assertion.
        name = min(PLACES, key=lambda p: (p[1]-lat)**2 + (p[2]-lon)**2)[0] + " vicinity"
    return {"display_name": name, "address": {"city_district": name}}
