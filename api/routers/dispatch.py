"""
POST /alerts/dispatch  — send SMS alerts to subscribers in affected areas.

Called hourly by cron-job.org (or any external cron service).
Protected by a Bearer token (DISPATCH_SECRET env var) so only your
cron job can trigger it — not the public.

Logic
-----
1. Fetch current per-cell alert levels (same as /forecast/alerts).
2. Load all active subscribers from Supabase.
3. For each subscriber, find their nearest grid cell → alert_level.
4. If alert_level is Watch or Warning:
   a. Check alert_log: already sent today at this level?  → skip.
   b. Not yet sent → send SMS via Africa's Talking, write to alert_log.
5. Return dispatch summary (dispatched, skipped, errors).

Deduplication
-------------
Each subscriber receives at most one Watch SMS and one Warning SMS per
calendar day (Lagos time, UTC+1).  If the alert escalates from Watch to
Warning on the same day, they receive a second message for the Warning.

Environment variables
---------------------
    DISPATCH_SECRET   — arbitrary secret string; set it in Render and in
                        the cron-job.org request header:
                        Authorization: Bearer <your-secret>
    SUPABASE_URL      — set in Render
    SUPABASE_KEY      — set in Render
    AT_USERNAME, AT_API_KEY, AT_SENDER_ID — Africa's Talking credentials
                        (set in Render; use username='sandbox' for testing)
"""

from __future__ import annotations

import logging
import os

import numpy as np
from fastapi import APIRouter, HTTPException, Request

log = logging.getLogger(__name__)

router = APIRouter(tags=["dispatch"])


# ---------------------------------------------------------------------------
# Bearer token auth (simple shared secret)
# ---------------------------------------------------------------------------

# Shared, constant-time implementation — see api/auth.py
from api.auth import require_dispatch_secret as _check_auth


# ---------------------------------------------------------------------------
# POST /alerts/dispatch
# ---------------------------------------------------------------------------

@router.post("/alerts/dispatch")
def dispatch_alerts(request: Request, dry_run: bool = False):
    """
    Compute current alert levels and send SMS to affected subscribers.

    This endpoint is meant to be called by an automated cron job every hour.
    Protect it with ``Authorization: Bearer <DISPATCH_SECRET>``.

    Response includes a per-subscriber breakdown to make it easy to diagnose
    why specific subscribers received or did not receive an SMS:

    - ``skipped_no_alert``: subscriber's nearest grid cell has No Alert
      right now (their area's risk class + current rainfall below threshold)
    - ``skipped_dedup``: already sent this alert level to them today

    Response::

        {
          "highest_alert":    "Watch",
          "dispatched":       12,
          "skipped_no_alert": 2,
          "skipped_dedup":    83,
          "errors":           0,
          "subscribers":      97,
          "event_date":       "2026-07-04",
          "subscriber_detail": [
            {"area": "Kosofe",   "level": "Watch",    "outcome": "sent"},
            {"area": "Lekki",    "level": "No Alert", "outcome": "skipped_no_alert"},
            ...
          ]
        }
    """
    _check_auth(request)

    if not dry_run and os.getenv("ALERT_DISPATCH_ENABLED", "false").lower() != "true":
        raise HTTPException(503, "Public SMS dispatch awaits pilot approval. Use dry_run=true to review the forecast.")

    # 1. Current alert levels for all grid cells
    from floodsight.alerts.engine import compute_alert_level
    from floodsight.forecast.rainfall_grid import (
        fetch_rainfall_grid,
        interpolate_to_cells,
        _try_imerg_observed,
    )
    from api.data_provider import get_grid
    from floodsight.db.supabase_client import (
        LAGOS_TZ,
        already_alerted,
        get_active_subscribers,
        get_recent_alert_levels,
        log_alert_sent,
        log_dispatch_cells,
        today_lagos,
    )
    from floodsight.notifications.sms import send_sms

    # One engine for dashboard AND messages, including coastal/dam upgrades.
    # The previous path passed the (observations, source) tuple as a dict and
    # omitted those upgrades, so SMS could disagree with the public map.
    from api.routers.forecast import get_grid_alerts
    from floodsight.config import PILOT_LAT, PILOT_LON
    alert_data = get_grid_alerts(PILOT_LAT, PILOT_LON)
    gdf, _ = get_grid()
    cell_alerts = alert_data["alert_levels"]
    if dry_run:
        return {"dry_run": True, "alert_counts": alert_data["alert_counts"], "highest_alert": alert_data["highest_alert"], "sent": 0}
    # 2. Build KD-tree from grid cell centroids (WGS84 lat/lon)
    gdf_wgs84 = gdf.to_crs("EPSG:4326")
    centroids  = gdf_wgs84.geometry.centroid
    grid_coords = np.column_stack([centroids.y, centroids.x])  # (lat, lon)
    cell_positions = {str(cell_id): i for i, cell_id in enumerate(gdf['cell_id'])}

    # 2b. Snapshot every Watch/Warning cell to Supabase. This is what
    # recalibration (scripts/recalibrate.py --analyse) compares field
    # verifications against — the alerts the system actually dispatched,
    # not dashboard clicks. Non-fatal: dispatch proceeds even if it fails.
    try:
        has_cell_id = "cell_id" in gdf.columns
        alerted_cells = [
            {
                "cell_id": str(gdf["cell_id"].iloc[i]) if has_cell_id else str(i),
                "lat": float(grid_coords[i][0]),
                "lon": float(grid_coords[i][1]),
                "alert_level": lvl,
            }
            for i, lvl in enumerate(cell_alerts)
            if lvl in ("Watch", "Warning")
        ]
        if alerted_cells:
            n_snap = log_dispatch_cells(today_lagos(), alerted_cells)
            log.info("Dispatch cell snapshot: %d Watch/Warning cells recorded", n_snap)
    except RuntimeError:
        log.warning("Supabase not configured — dispatch cell snapshot skipped")
    except Exception as exc:
        log.warning("Dispatch cell snapshot failed (non-fatal): %s", exc)

    # 3. Load subscribers
    try:
        subscribers = get_active_subscribers()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not subscribers:
        return {
            "highest_alert":    _highest(cell_alerts),
            "dispatched":       0,
            "skipped_no_alert": 0,
            "skipped_dedup":    0,
            "all_clear_sent":   0,
            "errors":           0,
            "subscribers":      0,
            "event_date":       today_lagos(),
            "subscriber_detail": [],
            "skipped":          0,
        }

    # 4. For each subscriber, find nearest cell → alert level → SMS
    event_date        = today_lagos()
    dispatched        = 0
    skipped_no_alert  = 0   # subscriber's area has no Watch/Warning right now
    skipped_dedup     = 0   # already sent this alert level to them today
    all_clear_sent    = 0   # stand-down messages after a recent alert
    errors            = 0
    subscriber_detail = []  # per-subscriber outcome for diagnostics
    no_alert_subs     = []  # (sub, sub_id, area) — evaluated for all-clear below

    for i, sub in enumerate(subscribers):
        # Older subscriber records may predate coverage validation.
        from api.coordinates import validate_location
        from api.data_provider import nearest_cell
        try:
            validate_location(sub["lat"], sub["lon"])
            cell = nearest_cell(sub["lat"], sub["lon"])
        except HTTPException:
            errors += 1
            subscriber_detail.append({"area": sub.get("area_name"), "outcome": "outside_coverage"})
            continue
        level  = cell_alerts[cell_positions[str(cell['cell_id'])]]
        sub_id = str(sub["id"])
        area   = sub.get("area_name") or "Unknown"

        if level == "No Alert":
            # Not skipped yet — the all-clear pass below decides whether
            # this subscriber gets a stand-down message (P2 item 9).
            no_alert_subs.append((sub, sub_id, area))
            continue

        if already_alerted(sub_id, level, event_date):
            skipped_dedup += 1
            subscriber_detail.append({
                "area":    area,
                "level":   level,
                "outcome": "skipped_already_sent_today",
            })
            continue

        # Send SMS
        try:
            if production():
                from floodsight.db.supabase_client import claim_alert
                if not claim_alert(sub_id, event_date, level):
                    skipped_dedup += 1
                    continue
            # Capture the AT recipient record so the messageId can be stored:
            # it is the only key that lets an inbound delivery report be
            # matched back to this alert_log row.
            at_recipient = send_sms(
                to_number   = sub["phone"],
                alert_level = level,
                area_name   = area,
            ) or {}
            log_alert_sent(
                sub_id, level, event_date,
                at_message_id = at_recipient.get("messageId"),
                at_status     = at_recipient.get("status"),
                at_cost       = at_recipient.get("cost"),
            )
            dispatched += 1
            subscriber_detail.append({
                "area":    area,
                "level":   level,
                "outcome": "sent",
            })
            log.info("Dispatched %s alert to subscriber %s", level, sub_id)
        except Exception as exc:
            errors += 1
            subscriber_detail.append({
                "area":    area,
                "level":   level,
                "outcome": f"error: {exc}",
            })
            log.error("SMS failed for subscriber %s (%s)", sub_id, type(exc).__name__)

    # 5. All-clear pass: subscribers whose cell is quiet NOW but who
    # received a Watch/Warning today or yesterday get ONE stand-down SMS
    # (deduplicated per day via alert_log, level 'All Clear' — requires
    # scripts/sql/04_inbound_otp.sql). Builds trust and reduces alarm
    # fatigue: residents learn alerts have an explicit end, not a fade-out.
    if no_alert_subs:
        from datetime import datetime, timedelta

        yesterday = (datetime.now(LAGOS_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")
        try:
            recent = get_recent_alert_levels([event_date, yesterday])
        except Exception as exc:
            log.warning("All-clear pass skipped — alert_log fetch failed: %s", exc)
            recent = []

        alerted_recently = {
            str(r["subscriber_id"]) for r in recent
            if r.get("alert_level") in ("Watch", "Warning")
        }
        allclear_today = {
            str(r["subscriber_id"]) for r in recent
            if r.get("alert_level") == "All Clear"
            and str(r.get("event_date")) == event_date
        }

        for sub, sub_id, area in no_alert_subs:
            if sub_id in alerted_recently and sub_id not in allclear_today:
                try:
                    if production():
                        from floodsight.db.supabase_client import claim_alert
                        if not claim_alert(sub_id, event_date, "All Clear"):
                            skipped_dedup += 1
                            continue
                    recipient = send_sms(
                        to_number   = sub["phone"],
                        alert_level = "All Clear",
                        area_name   = area,
                    )
                    log_alert_sent(sub_id, "All Clear", event_date,
                        at_message_id=(recipient or {}).get("messageId"),
                        at_status=(recipient or {}).get("status"))
                    all_clear_sent += 1
                    subscriber_detail.append({
                        "area":    area,
                        "level":   "All Clear",
                        "outcome": "all_clear_sent",
                    })
                    log.info("Threshold stand-down sent to subscriber %s", sub_id)
                except Exception as exc:
                    errors += 1
                    subscriber_detail.append({
                        "area":    area,
                        "level":   "All Clear",
                        "outcome": f"error: {exc}",
                    })
                    log.error("Threshold stand-down failed for subscriber %s (%s)", sub_id, type(exc).__name__)
            else:
                skipped_no_alert += 1
                subscriber_detail.append({
                    "area":    area,
                    "level":   "No Alert",
                    "outcome": "skipped_no_alert",
                })

    return {
        "highest_alert":    _highest(cell_alerts),
        "dispatched":       dispatched,
        "skipped_no_alert": skipped_no_alert,
        "skipped_dedup":    skipped_dedup,
        "all_clear_sent":   all_clear_sent,
        "errors":           errors,
        "subscribers":      len(subscribers),
        "event_date":       event_date,
        "subscriber_detail": subscriber_detail,
        # Legacy field kept for backward compatibility
        "skipped":          skipped_no_alert + skipped_dedup,
    }


def _highest(levels: list[str]) -> str:
    if "Warning" in levels: return "Warning"
    if "Watch"   in levels: return "Watch"
    return "No Alert"


# ---------------------------------------------------------------------------
# POST /alerts/test-sms  — send a test SMS to one number, bypassing weather
# ---------------------------------------------------------------------------

@router.post("/alerts/test-sms")
def test_sms(phone: str, request: Request):
    """
    Send a single test SMS to verify Africa's Talking credentials and delivery.
    Bypasses all weather/alert logic — always sends a 'Watch'-level message.

    Protected by the same DISPATCH_SECRET as /alerts/dispatch.

    Usage::

        curl -X POST "https://your-app.onrender.com/alerts/test-sms?phone=%2B2348012345678" \\
             -H "Authorization: Bearer <DISPATCH_SECRET>"

    Response::

        {"status": "sent", "phone": "+2348012345678", "mode": "live"}
    """
    _check_auth(request)

    from floodsight.notifications.sms import send_sms
    import os

    from api.runtime import production
    if production() and phone not in {p.strip() for p in os.getenv("APPROVED_TEST_PHONES", "").split(",") if p.strip()}:
        raise HTTPException(403, "Test messages are restricted to approved pilot numbers.")

    username = os.getenv("AT_USERNAME", "").strip()
    if not username:
        raise HTTPException(status_code=503, detail="AT_USERNAME not set in environment.")

    mode = "sandbox" if username == "sandbox" else "live"

    try:
        send_sms(
            to_number   = phone,
            alert_level = "Watch",
            area_name   = "Test Area",
        )
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"SMS failed: {exc}") from exc

    return {"status": "sent", "phone": phone, "mode": mode}


# ---------------------------------------------------------------------------
# POST /alerts/dispatch/force  — force Watch to ALL subscribers (testing)
# ---------------------------------------------------------------------------

@router.post("/alerts/dispatch/force")
def dispatch_force(request: Request):
    """
    Send a Watch-level SMS to ALL active subscribers regardless of current
    weather conditions.  Use for end-to-end testing before the first real event.

    Protected by DISPATCH_SECRET.  Does NOT write to alert_log so it won't
    block real alerts later.

    Response::

        {"dispatched": 3, "errors": 0, "subscribers": 3, "note": "force-send; no dedup log written"}
    """
    _check_auth(request)

    from api.runtime import production
    if production():
        raise HTTPException(403, "Bulk forced test messages are disabled in production.")

    from floodsight.db.supabase_client import get_active_subscribers
    from floodsight.notifications.sms import send_sms

    try:
        subscribers = get_active_subscribers()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not subscribers:
        return {"dispatched": 0, "errors": 0, "subscribers": 0,
                "note": "force-send; no dedup log written"}

    dispatched = 0
    errors     = 0
    for sub in subscribers:
        try:
            send_sms(
                to_number   = sub["phone"],
                alert_level = "Watch",
                area_name   = sub.get("area_name"),
            )
            dispatched += 1
            log.info("Force-sent test Watch to %s", sub["phone"])
        except Exception as exc:
            errors += 1
            log.error("Force-send failed for %s: %s", sub.get("phone"), exc)

    return {
        "dispatched":  dispatched,
        "errors":      errors,
        "subscribers": len(subscribers),
        "note":        "force-send; no dedup log written",
    }
