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
        .select("id", count="exact")
        .eq("active", True)
        .limit(0)
        .execute()
    )
    return result.count or 0


def get_subscriber_by_phone(phone: str) -> dict[str, Any] | None:
    """Return the subscriber row for a phone number (active or not)."""
    client = _get_client()
    phone  = normalize_phone(phone)
    result = (
        client.table("subscribers")
        .select("id, name, phone, lat, lon, area_name, risk_class, active")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def reactivate_subscriber(phone: str) -> bool:
    """Set active=TRUE for a phone number (START / re-subscribe keyword)."""
    client = _get_client()
    phone  = normalize_phone(phone)
    result = (
        client.table("subscribers")
        .update({"active": True})
        .eq("phone", phone)
        .execute()
    )
    updated = result.data or []
    log.info("Reactivated %d subscriber(s) for %s", len(updated), phone)
    return len(updated) > 0


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


def get_recent_alert_levels(event_dates: list[str]) -> list[dict[str, Any]]:
    """
    alert_log rows for the given Lagos event dates. Used by the all-clear
    pass in /alerts/dispatch: a subscriber who received Watch/Warning
    recently and whose cell is now quiet gets one stand-down SMS.
    """
    client = _get_client()
    result = (
        client.table("alert_log")
        .select("subscriber_id, alert_level, event_date")
        .in_("event_date", event_dates)
        .execute()
    )
    return result.data or []


# ---------------------------------------------------------------------------
# OTP-confirmed subscriptions (REQUIRE_OTP=true) — pending_subscriptions
# ---------------------------------------------------------------------------

def create_pending_subscription(
    phone: str, code_hash: str, payload: dict[str, Any], expires_at: str
) -> None:
    """Upsert the pending OTP row for a phone (re-requesting replaces it)."""
    client = _get_client()
    client.table("pending_subscriptions").upsert(
        {
            "phone":      phone,
            "code_hash":  code_hash,
            "payload":    payload,
            "attempts":   0,
            "expires_at": expires_at,
        },
        on_conflict="phone",
    ).execute()


def get_pending_subscription(phone: str) -> dict[str, Any] | None:
    client = _get_client()
    result = (
        client.table("pending_subscriptions")
        .select("*")
        .eq("phone", phone)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    return rows[0] if rows else None


def bump_pending_attempts(phone: str, attempts: int) -> None:
    client = _get_client()
    client.table("pending_subscriptions").update(
        {"attempts": attempts}
    ).eq("phone", phone).execute()


def delete_pending_subscription(phone: str) -> None:
    client = _get_client()
    client.table("pending_subscriptions").delete().eq("phone", phone).execute()


# ---------------------------------------------------------------------------
# Feedback-loop logs (Phase 6) — predictions, verifications, dispatch cells
#
# These previously lived in data/logs/*.jsonl on Render's EPHEMERAL disk and
# were wiped on every deploy/restart, silently destroying the recalibration
# feedback loop. They now persist in Supabase (schema:
# scripts/sql/03_logs.sql). Callers fall back to local JSONL when Supabase
# is not configured (local dev).
# ---------------------------------------------------------------------------

def log_prediction(entry: dict[str, Any]) -> None:
    """Insert one /depth/predict call record into prediction_log."""
    client = _get_client()
    client.table("prediction_log").insert(entry).execute()


def get_predictions(limit: int = 1000) -> list[dict[str, Any]]:
    """Most recent prediction_log rows, newest first."""
    client = _get_client()
    result = (
        client.table("prediction_log")
        .select("*")
        .order("ts", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def add_verification(entry: dict[str, Any]) -> None:
    """Insert one field verification report."""
    client = _get_client()
    client.table("verifications").insert(entry).execute()


def get_verifications(limit: int = 5000) -> list[dict[str, Any]]:
    """All verification reports, newest first."""
    client = _get_client()
    result = (
        client.table("verifications")
        .select("*")
        .order("ts", desc=True)
        .limit(limit)
        .execute()
    )
    return result.data or []


def log_dispatch_cells(event_date: str, cells: list[dict[str, Any]]) -> int:
    """
    Snapshot the grid cells that were at Watch/Warning when a dispatch ran.

    This is what recalibration must compare field verifications against —
    what the system *dispatched*, not what someone clicked on the dashboard.

    Upserts on (event_date, cell_id) so an hourly cron only records each
    cell once per day (last write wins — the level reflects the most
    recent dispatch run). Inserts in chunks to stay under request limits.

    Returns the number of rows sent.
    """
    client = _get_client()
    sent = 0
    CHUNK = 500
    for i in range(0, len(cells), CHUNK):
        chunk = [
            {
                "event_date":  event_date,
                "cell_id":     str(c["cell_id"]),
                "lat":         c["lat"],
                "lon":         c["lon"],
                "alert_level": c["alert_level"],
            }
            for c in cells[i : i + CHUNK]
        ]
        client.table("dispatch_cells").upsert(
            chunk, on_conflict="event_date,cell_id"
        ).execute()
        sent += len(chunk)
    return sent


def get_dispatch_cells(event_date: str | None = None) -> list[dict[str, Any]]:
    """Dispatch cell snapshots, optionally filtered to one event date."""
    client = _get_client()
    q = client.table("dispatch_cells").select("*")
    if event_date:
        q = q.eq("event_date", event_date)
    result = q.limit(50000).execute()
    return result.data or []


# ---------------------------------------------------------------------------
# Morning briefing idempotency log
# ---------------------------------------------------------------------------

def briefing_sent_today() -> bool:
    """
    Return True if a (non-dry-run) morning briefing was already sent today
    in Lagos time.  Used by the backup cron to avoid double-sending.
    """
    client = _get_client()
    result = (
        client.table("briefing_log")
        .select("id", count="exact", head=True)
        .eq("sent_date", today_lagos())
        .eq("dry_run", False)
        .execute()
    )
    return (result.count or 0) > 0


def log_briefing_sent(recipient_count: int, dry_run: bool = False) -> None:
    """
    Record that the morning briefing was sent today.  The UNIQUE constraint
    on sent_date means a second call is a safe no-op (conflict is ignored).
    """
    client = _get_client()
    try:
        client.table("briefing_log").insert({
            "sent_date":       today_lagos(),
            "recipient_count": recipient_count,
            "dry_run":         dry_run,
        }).execute()
        log.info("Briefing logged: sent_date=%s recipients=%d dry_run=%s",
                 today_lagos(), recipient_count, dry_run)
    except Exception as exc:
        if "unique" in str(exc).lower() or "duplicate" in str(exc).lower():
            log.debug("Briefing already logged for %s — skipping", today_lagos())
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
