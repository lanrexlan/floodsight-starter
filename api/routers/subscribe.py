"""
POST /subscribe            — register a new flood alert subscriber.
GET  /subscribers/count    — total active subscriber count.
GET  /subscribers/stats    — operator analytics: count by LGA, consent rate.
GET  /alerts/history       — recent dispatch history (operator dashboard).
DELETE /subscribe/{phone}  — deactivate (unsubscribe).

All subscriber data is stored in Supabase.
Requires SUPABASE_URL and SUPABASE_KEY environment variables.
Endpoints that need Supabase return synthetic demo data when it is unavailable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, field_validator

from api.data_provider import nearest_cell
from floodsight.db.supabase_client import (
    add_subscriber,
    deactivate_subscriber,
    get_subscriber_count,
    get_subscriber_stats,
    get_alert_history,
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
    consent:   bool = False  # NDPR: explicit consent required

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        try:
            return normalize_phone(v)
        except ValueError as exc:
            raise ValueError(str(exc)) from exc

    @field_validator("consent")
    @classmethod
    def must_consent(cls, v: bool) -> bool:
        if not v:
            raise ValueError(
                "Explicit consent is required to subscribe (NDPR compliance). "
                "Set consent=true to confirm the subscriber agrees to receive "
                "flood alert SMS and to their data being stored."
            )
        return v

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
            consent_at = datetime.now(timezone.utc).isoformat(),
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
# GET /subscribers/stats  (operator dashboard)
# ---------------------------------------------------------------------------

# Synthetic demo data used when Supabase is not configured.
_SYNTHETIC_STATS = {
    "total":        312,
    "active":       298,
    "by_area": [
        {"area": "Kosofe",   "count": 127},
        {"area": "Alimosho", "count":  89},
        {"area": "Eti-Osa",  "count":  82},
    ],
    "consent_rate": 0.98,
    "data_source":  "synthetic_demo",
}

_SYNTHETIC_HISTORY = {
    "dispatches": [
        {"event_date": "2026-07-01", "alert_level": "Red",    "recipients": 298, "delivered": 271, "delivery_rate": 0.91},
        {"event_date": "2026-06-28", "alert_level": "Orange", "recipients": 295, "delivered": 269, "delivery_rate": 0.91},
        {"event_date": "2026-06-21", "alert_level": "Orange", "recipients": 280, "delivered": 257, "delivery_rate": 0.92},
        {"event_date": "2026-06-14", "alert_level": "Red",    "recipients": 261, "delivered": 237, "delivery_rate": 0.91},
        {"event_date": "2026-06-07", "alert_level": "Yellow", "recipients": 244, "delivered": 225, "delivery_rate": 0.92},
        {"event_date": "2026-05-31", "alert_level": "Orange", "recipients": 218, "delivered": 199, "delivery_rate": 0.91},
        {"event_date": "2026-05-24", "alert_level": "Yellow", "recipients": 193, "delivered": 178, "delivery_rate": 0.92},
    ],
    "total_dispatches": 7,
    "data_source": "synthetic_demo",
}


@router.get("/subscribers/stats")
def subscriber_stats():
    """
    Operator dashboard: subscriber totals, breakdown by area, consent rate.

    Falls back to synthetic demo data when Supabase is not configured so the
    operator.html dashboard renders without error during demos.

    Response::

        {
          "total": 312,
          "active": 298,
          "by_area": [{"area": "Kosofe", "count": 127}, ...],
          "consent_rate": 0.98,
          "data_source": "supabase"   // or "synthetic_demo"
        }
    """
    try:
        return get_subscriber_stats()
    except RuntimeError:
        log.warning("Supabase not configured; returning synthetic subscriber stats")
        return _SYNTHETIC_STATS
    except Exception as exc:
        log.error("get_subscriber_stats failed: %s", exc)
        return _SYNTHETIC_STATS


# ---------------------------------------------------------------------------
# GET /alerts/history  (operator dashboard)
# ---------------------------------------------------------------------------

@router.get("/alerts/history")
def alert_history(limit: int = 20):
    """
    Operator dashboard: recent alert dispatch history.

    Groups alert_log by (event_date, alert_level) and counts recipients.
    Falls back to synthetic demo data when Supabase is not configured.

    Response::

        {
          "dispatches": [
            {
              "event_date": "2026-07-01",
              "alert_level": "Red",
              "recipients": 298,
              "delivered": 271,
              "delivery_rate": 0.91
            },
            ...
          ],
          "total_dispatches": 7,
          "data_source": "supabase"
        }
    """
    try:
        return get_alert_history(limit=limit)
    except RuntimeError:
        log.warning("Supabase not configured; returning synthetic alert history")
        return _SYNTHETIC_HISTORY
    except Exception as exc:
        log.error("get_alert_history failed: %s", exc)
        return _SYNTHETIC_HISTORY


# ---------------------------------------------------------------------------
# DELETE /subscribe/{phone}
# ---------------------------------------------------------------------------

@router.delete("/subscribe/{phone}")
def unsubscribe(phone: str):
    """
    Deactivate a subscriber by phone number.
    Africa's Talking STOP keyword also triggers deactivation via webhook.

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
