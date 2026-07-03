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
   b. Not yet sent → send SMS via Twilio, write to alert_log.
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
from scipy.spatial import cKDTree

log = logging.getLogger(__name__)

router = APIRouter(tags=["dispatch"])


# ---------------------------------------------------------------------------
# Bearer token auth (simple shared secret)
# ---------------------------------------------------------------------------

def _check_auth(request: Request) -> None:
    secret = os.getenv("DISPATCH_SECRET", "").strip()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="DISPATCH_SECRET environment variable not set.",
        )
    auth_header = request.headers.get("Authorization", "")
    if auth_header != f"Bearer {secret}":
        raise HTTPException(status_code=401, detail="Unauthorized.")


# ---------------------------------------------------------------------------
# POST /alerts/dispatch
# ---------------------------------------------------------------------------

@router.post("/alerts/dispatch")
def dispatch_alerts(request: Request):
    """
    Compute current alert levels and send SMS to affected subscribers.

    This endpoint is meant to be called by an automated cron job every hour.
    Protect it with ``Authorization: Bearer <DISPATCH_SECRET>``.

    Response::

        {
          "highest_alert":  "Watch",
          "dispatched":     12,
          "skipped":        85,
          "errors":         0,
          "subscribers":    97,
          "event_date":     "2026-06-30"
        }
    """
    _check_auth(request)

    # 1. Current alert levels for all grid cells
    from floodsight.alerts.engine import compute_alert_level
    from floodsight.forecast.rainfall_grid import (
        fetch_rainfall_grid,
        interpolate_to_cells,
        _try_imerg_observed,
    )
    from api.data_provider import get_grid
    from floodsight.db.supabase_client import (
        already_alerted,
        get_active_subscribers,
        log_alert_sent,
        today_lagos,
    )
    from floodsight.notifications.sms import send_sms

    try:
        rainfall_grid = fetch_rainfall_grid()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=f"Rainfall fetch failed: {exc}") from exc

    imerg_obs  = _try_imerg_observed()
    gdf, _     = get_grid()
    cell_rain  = interpolate_to_cells(gdf, rainfall_grid, imerg_obs)

    cell_alerts = [
        compute_alert_level(rc, r24, r72)
        for rc, r24, r72 in zip(
            gdf["risk_class"],
            cell_rain["rain_24h_mm"],
            cell_rain["rain_72h_mm"],
        )
    ]

    # 2. Build KD-tree from grid cell centroids (WGS84 lat/lon)
    gdf_wgs84 = gdf.to_crs("EPSG:4326")
    centroids  = gdf_wgs84.geometry.centroid
    grid_coords = np.column_stack([centroids.y, centroids.x])  # (lat, lon)
    tree        = cKDTree(grid_coords)

    # 3. Load subscribers
    try:
        subscribers = get_active_subscribers()
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not subscribers:
        return {
            "highest_alert": _highest(cell_alerts),
            "dispatched":    0,
            "skipped":       0,
            "errors":        0,
            "subscribers":   0,
            "event_date":    today_lagos(),
        }

    # 4. For each subscriber, find nearest cell → alert level → SMS
    event_date  = today_lagos()
    dispatched  = 0
    skipped     = 0
    errors      = 0

    sub_coords = np.array([[s["lat"], s["lon"]] for s in subscribers])
    _, nearest_idx = tree.query(sub_coords, k=1)

    for i, sub in enumerate(subscribers):
        level = cell_alerts[nearest_idx[i]]

        if level == "No Alert":
            skipped += 1
            continue

        sub_id = str(sub["id"])
        if already_alerted(sub_id, level, event_date):
            skipped += 1
            continue

        # Send SMS
        try:
            send_sms(
                to_number  = sub["phone"],
                alert_level= level,
                area_name  = sub.get("area_name"),
            )
            log_alert_sent(sub_id, level, event_date)
            dispatched += 1
            log.info(
                "Dispatched %s alert to %s (%s)",
                level, sub["phone"], sub.get("area_name", "?"),
            )
        except Exception as exc:
            errors += 1
            log.error(
                "SMS failed for %s: %s", sub.get("phone", "?"), exc
            )

    return {
        "highest_alert": _highest(cell_alerts),
        "dispatched":    dispatched,
        "skipped":       skipped,
        "errors":        errors,
        "subscribers":   len(subscribers),
        "event_date":    event_date,
    }


def _highest(levels: list[str]) -> str:
    if "Warning" in levels: return "Warning"
    if "Watch"   in levels: return "Watch"
    return "No Alert"
