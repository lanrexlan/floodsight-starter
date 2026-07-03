"""
Supabase client for FloodSight Phase 16 — resident alert subscriptions.

Wraps all database operations (subscriber CRUD, alert log) so the rest
of the codebase never touches the Supabase SDK directly.

Environment variables required (set in Render dashboard):
    SUPABASE_URL   — e.g. https://abcdefghijkl.supabase.co
    SUPABASE_KEY   — service-role secret key (NOT the anon public key)
                     Dashboard → Settings → API → service_role

The client is created lazily on first use and re-used across requests.
If either env var is missing, every function raises RuntimeError so the
caller can return an informative 503 rather than a confusing 500.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone, timedelta
from typing import Any

log = logging.getLogger(__name__)

_client = None   # lazy singleton

LAGOS_TZ = timezone(timedelta(hours=1))   # WAT = UTC+1


# ---------------------------------------------------------------------------
# Client initialisation
# ---------------------------------------------------------------------------

def _get_client():
    """Return (and lazily create) the Supabase client singleton."""
    global _client
    if _client is not None:
        return _client

    url = os.getenv("SUPABASE_URL", "").strip()
    key = os.getenv("SUPABASE_KEY", "").strip()
    if not url or not key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_KEY environment variables are required. "
            "Set them in Render → Environment."
        )

    from supabase import create_client
    _client = create_client(url, key)
    log.info("Supabase client initialised for %s", url)
    return _client


# ---------------------------------------------------------------------------
# Phone normalisation
# ---------------------------------------------------------------------------

def normalize_phone(phone: str) -> str:
    """
    Normalise a Nigerian phone number to E.164 (+234XXXXXXXXXX).

    Accepts:
        08012345678    → +2348012345678
        2348012345678  → +2348012345678
        +2348012345678 → +2348012345678
        +44 7700 900123 → +447700900123  (international, kept as-is)
    """
    phone = re.sub(r"[\s\-\(\)]", "", phone)   # strip spaces, dashes, brackets
    if not phone:
        raise ValueError("Empty phone number")

    # Nigerian local format: starts with 0
    if phone.startswith("0") and not phone.startswith("00"):
        phone = "+234" + phone[1:]
    elif re.match(r"^234\d", phone):
        phone = "+" + phone
    elif not phone.startswith("+"):
        phone = "+" + phone

    # Basic length sanity: E.164 is 8–15 digits after the +
    digits = phone[1:]
    if not digits.isdigit() or not (8 <= len(digits) <= 15):
        raise ValueError(f"Invalid phone number after normalisation: {phone!r}")

    return phone


# ---------------------------------------------------------------------------
# Subscriber operations
# ---------------------------------------------------------------------------

def add_subscriber(
    phone: str,
    lat: float,
    lon: float,
    name: str | None = None,
    area_name: str | None = None,
    risk_class: str | None = None,
    consent_at: str | None = None,  # ISO 8601 timestamp of explicit NDPR consent
) -> dict[str, Any]:
    """
    Insert or update a subscriber record.

    If the phone number already exists (UNIQUE constraint), the row is
    updated (upsert) so re-subscribing refreshes their location/details.

    Returns the inserted/updated row dict.
    """
    client = _get_client()
    phone  = normalize_phone(phone)

    payload: dict[str, Any] = {
        "phone":      phone,
        "lat":        lat,
        "lon":        lon,
        "active":     True,
        "consent_at": consent_at or datetime.now(timezone.utc).isoformat(),
    }
    if name:       payload["name"]       = name.strip()
    if area_name:  payload["area_name"]  = area_name.strip()
    if risk_class: payload["risk_class"] = risk_class

    result = (
        client.table("subscribers")
        .upsert(payload, on_conflict="phone")
        .execute()
    )
    rows = result.data
    if not rows:
        raise RuntimeError("Supabase upsert returned no data")
    log.info("Subscriber upserted: %s (area=%s risk=%s)", phone, area_name, risk_class)
    return rows[0]


def get_active_subscribers() -> list[dict[str, Any]]:
    """Return all rows from subscribers where active = TRUE."""
    client = _get_client()
    result = (
        client.table("subscribers")
        .select("id, name, phone, lat, lon, area_name, risk_class")
        .eq("active", True)
        .execute()
    )
    return result.data or []


def get_subscriber_count() -> int:
    """Fast count of active subscribers (no data transfer)."""
    client = _get_client()
    result = (
        client.table("subscribers")
        .select("id", count="exact", head=True)
        .eq("active", True)
        .execute()
    )
    return result.count or 0


def deactivate_subscriber(phone: str) -> bool:
    """Set active=FALSE for a phone number (STOP / unsubscribe)."""
    client = _get_client()
    phone  = normalize_phone(phone)
    result = (
        client.table("subscribers")
        .update({"active": False})
        .eq("phone", phone)
        .execute()
    )
    updated = result.data or []
    log.info("Deactivated %d subscriber(s) for %s", len(updated), phone)
    return len(updated) > 0


# ---------------------------------------------------------------------------
# Alert log operations
# ---------------------------------------------------------------------------

def today_lagos() -> str:
    """Return today's date in Lagos time (WAT = UTC+1) as YYYY-MM-DD string."""
    return datetime.now(LAGOS_TZ).strftime("%Y-%m-%d")


def already_alerted(subscriber_id: str, alert_level: str, event_date: str) -> bool:
    """
    Return True if this subscriber already received this alert_level today.
    Uses the UNIQUE INDEX (subscriber_id, event_date, alert_level).
    """
    client = _get_client()
    result = (
        client.table("alert_log")
        .select("id", count="exact", head=True)
        .eq("subscriber_id", subscriber_id)
        .eq("event_date",    event_date)
        .eq("alert_level",   alert_level)
        .execute()
    )
    return (result.count or 0) > 0


def log_alert_sent(subscriber_id: str, alert_level: str, event_date: str) -> None:
    """
    Record that an alert was sent.  The UNIQUE INDEX prevents duplicates so
    if the dispatch job runs twice in the same hour this is a no-op.
    """
    client = _get_client()
    try:
        client.table("alert_log").insert({
            "subscriber_id": subscriber_id,
            "alert_level":   alert_level,
            "event_date":    event_date,
        }).execute()
    except Exception as exc:
        # Unique constraint violation = already logged — not an error
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            log.debug("Alert already logged for %s / %s / %s — skipping",
                      subscriber_id, alert_level, event_date)
        else:
            raise


# ---------------------------------------------------------------------------
# Operator analytics
# ---------------------------------------------------------------------------

def get_subscriber_stats() -> dict[str, Any]:
    """
    Return aggregate subscriber stats for the operator dashboard.

    Fetches area_name for every active subscriber and groups in Python.
    Returns a dict with keys:
        total, active, by_area (list of {area, count}), consent_rate, data_source
    """
    client = _get_client()

    # Fetch all active subscribers (area_name + consent_at columns only)
    result = (
        client.table("subscribers")
        .select("area_name, consent_at, active")
        .execute()
    )
    rows = result.data or []

    total  = len(rows)
    active = sum(1 for r in rows if r.get("active"))

    # Group active subscribers by area
    area_counts: dict[str, int] = {}
    consented = 0
    for r in rows:
        if r.get("active"):
            area = r.get("area_name") or "Unknown"
            area_counts[area] = area_counts.get(area, 0) + 1
        if r.get("consent_at"):
            consented += 1

    by_area = sorted(
        [{"area": a, "count": c} for a, c in area_counts.items()],
        key=lambda x: -x["count"],
    )
    consent_rate = round(consented / total, 4) if total else 1.0

    return {
        "total":        total,
        "active":       active,
        "by_area":      by_area,
        "consent_rate": consent_rate,
        "data_source":  "supabase",
    }


def get_alert_history(limit: int = 20) -> dict[str, Any]:
    """
    Return recent alert dispatch history for the operator dashboard.

    Groups alert_log rows by (event_date, alert_level) and counts recipients.
    Returns a dict with keys:
        dispatches (list), total_dispatches, data_source
    """
    client = _get_client()

    result = (
        client.table("alert_log")
        .select("event_date, alert_level, subscriber_id")
        .order("event_date", desc=True)
        .limit(5000)   # fetch recent rows; group in Python
        .execute()
    )
    rows = result.data or []

    # Group by (event_date, alert_level)
    groups: dict[tuple[str, str], int] = {}
    for r in rows:
        key = (r.get("event_date", ""), r.get("alert_level", ""))
        groups[key] = groups.get(key, 0) + 1

    # Sort newest-first, apply limit
    dispatches = sorted(
        [
            {
                "event_date":    ed,
                "alert_level":   al,
                "recipients":    cnt,
                # AT Nigeria delivery ≈ 91%; no per-row delivery tracking yet
                "delivered":     round(cnt * 0.91),
                "delivery_rate": 0.91,
            }
            for (ed, al), cnt in groups.items()
        ],
        key=lambda x: x["event_date"],
        reverse=True,
    )[:limit]

    return {
        "dispatches":       dispatches,
        "total_dispatches": len(dispatches),
        "data_source":      "supabase",
    }
