"""
POST /subscribe  — register a new flood alert subscriber.
GET  /subscribers/count  — number of active subscribers (for dashboard display).
DELETE /subscribe/{phone} — deactivate (unsubscribe).

All subscriber data is stored in Supabase.
Requires SUPABASE_URL and SUPABASE_KEY environment variables.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from api.data_provider import nearest_cell
from floodsight.db.supabase_client import (
    add_subscriber,
    deactivate_subscriber,
    get_subscriber_count,
    normalize_phone,
)

log = logging.getLogger(__name__)

router = APIRouter(tags=["subscriptions"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class SubscribeRequest(BaseModel):
    phone:     str
    lat:       float
    lon:       float
    name:      str | None = None
    area_name: str | None = None

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        try:
            return normalize_phone(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("lat")
    @classmethod
    def validate_lat(cls, v: float) -> float:
        if not (-90 <= v <= 90):
            raise ValueError("lat must be between -90 and 90")
        return v

    @field_validator("lon")
    @classmethod
    def validate_lon(cls, v: float) -> float:
        if not (-180 <= v <= 180):
            raise ValueError("lon must be between -180 and 180")
        return v


# ---------------------------------------------------------------------------
# POST /subscribe
# ---------------------------------------------------------------------------

@router.post("/subscribe")
def subscribe(req: SubscribeRequest):
    """
    Register a resident for SMS flood alerts.

    The subscriber's lat/lon is used to find their nearest grid cell;
    the cell's ``risk_class`` is returned so the form can show them
    their area's baseline risk level immediately after sign-up.

    The same endpoint can be called again to update a subscriber's
    location — the phone number is the unique key (upsert).

    Response::

        {
          "status": "subscribed",
          "phone": "+2348012345678",
          "risk_class": "High",
          "area_name": "Kosofe"
        }
    """
    # Look up the nearest grid cell to get risk class
    try:
        cell       = nearest_cell(req.lat, req.lon)
        risk_class = str(cell["risk_class"])
    except Exception as exc:
        log.warning("nearest_cell failed for (%s, %s): %s", req.lat, req.lon, exc)
        risk_class = None

    # Persist to Supabase
    try:
        row = add_subscriber(
            phone      = req.phone,
            lat        = req.lat,
            lon        = req.lon,
            name       = req.name,
            area_name  = req.area_name,
            risk_class = risk_class,
        )
    except RuntimeError as exc:
        # Missing env vars — Supabase not configured
        log.error("Supabase not configured: %s", exc)
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        log.error("Supabase insert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Could not save subscription.") from exc

    return {
        "status":     "subscribed",
        "phone":      row["phone"],
        "risk_class": risk_class,
        "area_name":  row.get("area_name") or req.area_name,
    }


# ---------------------------------------------------------------------------
# GET /subscribers/count
# ---------------------------------------------------------------------------

@router.get("/subscribers/count")
def subscriber_count():
    """
    Returns the total number of active subscribers.
    Shown in the operator dashboard to track adoption.

    Response::

        {"active_subscribers": 127}
    """
    try:
        count = get_subscriber_count()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    return {"active_subscribers": count}


# ---------------------------------------------------------------------------
# DELETE /subscribe/{phone}
# ---------------------------------------------------------------------------

@router.delete("/subscribe/{phone}")
def unsubscribe(phone: str):
    """
    Deactivate a subscriber by phone number.
    Twilio's built-in STOP handling also covers opt-outs for SMS.

    Response::

        {"status": "unsubscribed", "phone": "+2348012345678"}
    """
    try:
        norm  = normalize_phone(phone)
        found = deactivate_subscriber(norm)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    if not found:
        raise HTTPException(status_code=404, detail="Phone number not found.")

    return {"status": "unsubscribed", "phone": norm}
