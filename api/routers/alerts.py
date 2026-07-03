from __future__ import annotations

from fastapi import APIRouter

from api.data_provider import get_grid, nearest_cell
from api.schemas import AlertRequest, AlertResponse
from floodsight.alerts.engine import compute_alert_level

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.post("/current", response_model=AlertResponse)
def current_alert(req: AlertRequest):
    cell = nearest_cell(req.lat, req.lon)
    _, source = get_grid()

    level = compute_alert_level(
        risk_class=str(cell["risk_class"]),
        rain_24h_mm=req.rain_24h_mm,
        rain_72h_mm=req.rain_72h_mm,
        predicted_depth_m=req.predicted_depth_m,
    )

    return AlertResponse(
        lat=req.lat,
        lon=req.lon,
        risk_class=str(cell["risk_class"]),
        alert_level=level,
        rain_24h_mm=req.rain_24h_mm,
        rain_72h_mm=req.rain_72h_mm,
        data_source=source,
    )
