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

import hmac
import logging
import secrets as pysecrets
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field, field_validator
from api.schemas import LocatedInput

from api.auth import require_dispatch_secret
from api.data_provider import nearest_cell
from floodsight.db.supabase_client import (
    add_subscriber,
    bump_pending_attempts,
    create_pending_subscription,
    deactivate_subscriber,
    delete_pending_subscription,
    get_pending_subscription,
    get_subscriber_count,
    get_subscriber_stats,
    get_alert_history,
    normalize_phone,
)

# ---------------------------------------------------------------------------
# OTP confirmation (P2 item 10 — closes the upsert-hijack hole)
#
# When REQUIRE_OTP=true, POST /subscribe no longer writes the subscriber
# directly: it stores a pending record + texts a 6-digit code, and only
# POST /subscribe/confirm (phone + code) completes the upsert. Without
# this, anyone who knows a resident's phone number could silently move
# that resident's alert location.
#
# Default is OFF so existing deployments/dashboards keep working until the
# flow has been tested end-to-end in the AT sandbox.
# Helpers live in api/otp.py (unit-testable without the geo stack).
# ---------------------------------------------------------------------------

from api.otp import OTP_MAX_ATTEMPTS, OTP_TTL_MINUTES
from api.otp import hash_code as _hash_code
from api.otp import otp_required as _otp_required

import time as _time
from collections import defaultdict

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# In-memory rate limiter (IMPROVEMENTS item 13 — /subscribe is an SMS-cost
# attack surface; Render is single-process so a module-level dict is enough)
# ---------------------------------------------------------------------------
_phone_windows: dict = defaultdict(list)
_ip_windows:    dict = defaultdict(list)
_PHONE_MAX, _PHONE_TTL = 3, 600   # 3 attempts per phone per 10 min
_IP_MAX,    _IP_TTL    = 15, 60   # 15 attempts per IP per 1 min


def _rate_check(phone: str, ip: str) -> None:
    """Raise HTTP 429 if phone or IP exceeds the subscribe rate limit."""
    from api.runtime import production
    if production():
        from floodsight.db.supabase_client import consume_subscription_attempt
        try:
            allowed = consume_subscription_attempt(phone, ip)
        except Exception as exc:
            raise HTTPException(503, "Subscription service is temporarily unavailable.") from exc
        if not allowed:
            raise HTTPException(429, "Too many subscription attempts.", headers={"Retry-After": "600"})
        return
    now = _time.monotonic()
    for windows in (_phone_windows, _ip_windows):
        if len(windows) > 10000:
            windows.clear()
    wins = [t for t in _phone_windows[phone] if now - t < _PHONE_TTL]
    _phone_windows[phone] = wins
    if len(wins) >= _PHONE_MAX:
        raise HTTPException(
            status_code=429,
            detail=f"Too many subscription requests. Try again in {_PHONE_TTL // 60} minutes.",
            headers={"Retry-After": str(_PHONE_TTL)},
        )
    _phone_windows[phone].append(now)
    wins = [t for t in _ip_windows[ip] if now - t < _IP_TTL]
    _ip_windows[ip] = wins
    if len(wins) >= _IP_MAX:
        raise HTTPException(
            status_code=429,
            detail="Too many requests from this address. Please slow down.",
            headers={"Retry-After": str(_IP_TTL)},
        )
    _ip_windows[ip].append(now)


router = APIRouter(tags=["subscriptions"])


# ---------------------------------------------------------------------------
# Request / response schemas
# ---------------------------------------------------------------------------

class SubscribeRequest(LocatedInput):
    phone:     str = Field(max_length=32)
    name:      str | None = Field(default=None, max_length=120)
    area_name: str | None = Field(default=None, max_length=200)
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
def subscribe(req: SubscribeRequest, request: Request):
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
    With ``REQUIRE_OTP=true`` this endpoint instead texts a 6-digit code
    and returns ``{"status": "pending_confirmation"}`` — the subscription
    is only written after POST /subscribe/confirm.
    """
    _rate_check(req.phone, request.client.host if request.client else "unknown")
    # Check actual cell coverage before storing a pending record or sending SMS.
    signup_cell = nearest_cell(req.lat, req.lon)
    if _otp_required():
        code = f"{pysecrets.randbelow(10**6):06d}"
        expires = (
            datetime.now(timezone.utc) + timedelta(minutes=OTP_TTL_MINUTES)
        ).isoformat()
        try:
            create_pending_subscription(
                phone     = req.phone,
                code_hash = _hash_code(code, req.phone),
                payload   = {
                    "lat":       req.lat,
                    "lon":       req.lon,
                    "name":      req.name,
                    "area_name": req.area_name,
                    "risk_class": str(signup_cell["risk_class"]),
                },
                expires_at = expires,
            )
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

        try:
            from floodsight.notifications.sms import send_otp

            send_otp(req.phone, code)
        except Exception as exc:
            log.error("OTP SMS failed for %s: %s", req.phone, exc)
            raise HTTPException(
                status_code=502, detail="Could not send confirmation code."
            ) from exc

        return {
            "status":          "pending_confirmation",
            "phone":           req.phone,
            "expires_minutes": OTP_TTL_MINUTES,
        }

    return _complete_subscription(
        phone=req.phone, lat=req.lat, lon=req.lon,
        name=req.name, area_name=req.area_name,
    )


def _complete_subscription(
    phone: str, lat: float, lon: float,
    name: str | None, area_name: str | None, confirmed_row: dict | None = None,
) -> dict:
    """Nearest-cell lookup + Supabase upsert — shared by both flows."""
    try:
        cell       = nearest_cell(lat, lon)
        risk_class = str(cell["risk_class"])
    except Exception as exc:
        if isinstance(exc, HTTPException):
            raise
        log.warning("nearest_cell failed for (%s, %s): %s", lat, lon, exc)
        risk_class = None

    try:
        row = confirmed_row or add_subscriber(
            phone      = phone,
            lat        = lat,
            lon        = lon,
            name       = name,
            area_name  = area_name,
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

    # ------------------------------------------------------------------
    # Welcome SMS.
    #
    # Previously the subscriber row was written and the endpoint returned
    # without sending anything, so residents who signed up on floodsight.html
    # saw a success message but never received an SMS — they had no way to
    # tell whether the number had registered correctly, and no delivery
    # confirmation until the next Watch/Warning dispatch (potentially weeks).
    #
    # Deliberately non-blocking: a failed welcome SMS must not roll back or
    # 500 a subscription that is already committed to Supabase. We log and
    # report delivery status in the response instead.
    # ------------------------------------------------------------------
    welcome_sent = False
    try:
        from floodsight.notifications.africastalking import send_sms as _at_send

        area = (row.get("area_name") or area_name or "your area").strip()

        # Compose to fit ONE GSM-7 segment (<=160 chars) so every welcome
        # message bills as a single SMS. The opt-out suffix is required on
        # every message (NDPR) and is never truncated — the area name is
        # dropped first if a pathological name would overflow the budget.
        suffix = " Reply STOP to opt out"
        head   = f"FloodSight: {phone} is registered for flood alerts"
        tail   = ". We will text you when a Watch or Warning is issued."

        body = f"{head} in {area}{tail}"
        if len(body) + len(suffix) > 160:
            body = f"{head}{tail}"
        if len(body) + len(suffix) > 160:
            body = body[: 160 - len(suffix)].rsplit(" ", 1)[0]
        body += suffix

        _at_send(message=body, recipients=[phone])
        welcome_sent = True
        log.info("Welcome SMS sent to %s (%s)", phone, area)
    except Exception as exc:
        log.error("Welcome SMS failed for %s: %s", phone, exc)

    return {
        "status":       "subscribed",
        "phone":        row["phone"],
        "risk_class":   risk_class,
        "area_name":    row.get("area_name") or area_name,
        "welcome_sent": welcome_sent,
    }


class ConfirmRequest(BaseModel):
    phone: str
    code:  str

    @field_validator("phone")
    @classmethod
    def validate_phone(cls, v: str) -> str:
        return normalize_phone(v)

    @field_validator("code")
    @classmethod
    def validate_code(cls, v: str) -> str:
        v = v.strip()
        if not (v.isdigit() and len(v) == 6):
            raise ValueError("code must be 6 digits")
        return v


@router.post("/subscribe/confirm")
def confirm_subscription(req: ConfirmRequest, request: Request):
    """
    Complete an OTP-pending subscription (REQUIRE_OTP flow).

    Errors: 404 no pending request | 410 code expired |
    429 too many attempts | 401 wrong code.
    """
    _rate_check(req.phone, request.client.host if request.client else "unknown")
    from api.runtime import production
    if production():
        from floodsight.db.supabase_client import consume_pending_subscription
        try:
            result = consume_pending_subscription(req.phone, _hash_code(req.code, req.phone))
        except Exception as exc:
            raise HTTPException(503, "Could not verify confirmation code; retry later.") from exc
        status = result.get("status")
        if status != "confirmed":
            code, detail = {"expired": (410,"Code expired; subscribe again."),
                            "limited": (429,"Too many attempts; subscribe again."),
                            "wrong": (401,"Wrong code.")}.get(status, (404,"No pending subscription."))
            raise HTTPException(code, detail)
        row = result["subscriber"]
        return _complete_subscription(req.phone, row["lat"], row["lon"], row.get("name"), row.get("area_name"), confirmed_row=row)
    try:
        pending = get_pending_subscription(req.phone)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not pending:
        raise HTTPException(status_code=404, detail="No pending subscription for this number.")

    expires_at = str(pending.get("expires_at", ""))
    try:
        exp = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    except ValueError:
        exp = datetime.now(timezone.utc) - timedelta(seconds=1)
    if datetime.now(timezone.utc) > exp:
        delete_pending_subscription(req.phone)
        raise HTTPException(status_code=410, detail="Code expired — subscribe again.")

    attempts = int(pending.get("attempts", 0))
    if attempts >= OTP_MAX_ATTEMPTS:
        delete_pending_subscription(req.phone)
        raise HTTPException(status_code=429, detail="Too many attempts — subscribe again.")

    if not hmac.compare_digest(
        _hash_code(req.code, req.phone), str(pending.get("code_hash", ""))
    ):
        bump_pending_attempts(req.phone, attempts + 1)
        raise HTTPException(status_code=401, detail="Wrong code.")

    payload = pending.get("payload") or {}
    delete_pending_subscription(req.phone)
    return _complete_subscription(
        phone     = req.phone,
        lat       = float(payload.get("lat")),
        lon       = float(payload.get("lon")),
        name      = payload.get("name"),
        area_name = payload.get("area_name"),
    )


@router.delete("/subscribe/{phone}/erase")
def erase_subscription(phone: str, request: Request):
    require_dispatch_secret(request)
    try:
        phone = normalize_phone(phone)
    except ValueError as exc:
        raise HTTPException(422, "Invalid phone number.") from exc
    from floodsight.db.supabase_client import erase_subscriber
    try:
        erase_subscriber(phone)
    except Exception as exc:
        raise HTTPException(503, "Erasure could not be completed; retry later.") from exc
    return {"status": "erased"}


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
        return {"active_subscribers": count}
    except RuntimeError as exc:
        # Supabase not configured — return null rather than 503 so the
        # dashboard badge stays blank instead of logging a noisy error.
        log.warning("subscriber_count: Supabase not configured: %s", exc)
        return {"active_subscribers": None, "data_source": "unavailable"}
    except Exception as exc:
        # Supabase API error (table missing, auth, network) — degrade gracefully.
        log.warning("subscriber_count: Supabase error (non-fatal): %s", exc)
        return {"active_subscribers": None, "data_source": "unavailable"}


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
        {"event_date": "2026-07-01", "alert_level": "Warning",    "recipients": 298, "delivered": 271, "delivery_rate": 0.91},
        {"event_date": "2026-06-28", "alert_level": "Watch", "recipients": 295, "delivered": 269, "delivery_rate": 0.91},
        {"event_date": "2026-06-21", "alert_level": "Watch", "recipients": 280, "delivered": 257, "delivery_rate": 0.92},
        {"event_date": "2026-06-14", "alert_level": "Warning",    "recipients": 261, "delivered": 237, "delivery_rate": 0.91},
        {"event_date": "2026-06-07", "alert_level": "Watch", "recipients": 244, "delivered": 225, "delivery_rate": 0.92},
        {"event_date": "2026-05-31", "alert_level": "Watch", "recipients": 218, "delivered": 199, "delivery_rate": 0.91},
        {"event_date": "2026-05-24", "alert_level": "Watch", "recipients": 193, "delivered": 178, "delivery_rate": 0.92},
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
        from api.runtime import require_durable_storage
        require_durable_storage()
        log.warning("Supabase not configured; returning synthetic subscriber stats")
        return _SYNTHETIC_STATS
    except Exception as exc:
        log.error("get_subscriber_stats failed: %s", exc)
        from api.runtime import require_durable_storage
        require_durable_storage()
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
              "alert_level": "Warning",
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
        from api.runtime import require_durable_storage
        require_durable_storage()
        return _SYNTHETIC_HISTORY
    except Exception as exc:
        log.error("get_alert_history failed: %s", exc)
        from api.runtime import require_durable_storage
        require_durable_storage()
        return _SYNTHETIC_HISTORY


# ---------------------------------------------------------------------------
# DELETE /subscribe/{phone}
# ---------------------------------------------------------------------------

@router.delete("/subscribe/{phone}")
def unsubscribe(phone: str, request: Request):
    """
    Deactivate a subscriber by phone number.

    Operator-only: requires ``Authorization: Bearer <DISPATCH_SECRET>``.
    This endpoint was previously unauthenticated, which let anyone on the
    internet unsubscribe any resident from flood warnings by guessing or
    enumerating phone numbers — unacceptable for a life-safety system.

    Residents self-unsubscribe by replying STOP to any alert SMS (inbound
    webhook pending — IMPROVEMENTS.md item 10).

    Response::

        {"status": "unsubscribed", "phone": "+2348012345678"}
    """
    require_dispatch_secret(request)

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
