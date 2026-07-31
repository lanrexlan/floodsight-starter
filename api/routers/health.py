"""
FloodSight Health Intelligence API.

GET  /health/risk              — Current LGA outbreak probability scores
GET  /health/risk/{lga_name}   — Single LGA score
POST /health/chew-response     — Receive CHEW SMS reply (Africa's Talking webhook)
GET  /health/mel/summary       — Aggregated MEL statistics

Register in api/main.py:
    from api.routers import health
    app.include_router(health.router)

Africa's Talking inbound webhook setup:
    Dashboard → SMS → Inbox → Callback URL
    POST https://<render-url>/health/chew-response

Supported CHEW reply keywords
    CONFIRM        → CHEW confirms receipt and intent to act
    REPORT <N>     → CHEW reports N malaria cases seen this week
    HELP           → CHEW requests a callback / more information
"""

from __future__ import annotations

import logging
from datetime import date

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

log = logging.getLogger(__name__)

router = APIRouter(prefix="/health", tags=["health"])


# ---------------------------------------------------------------------------
# /health/risk  —  LGA outbreak probability (all LGAs or single)
# ---------------------------------------------------------------------------

@router.get("/risk")
def get_health_risk():
    """
    Return today's LGA outbreak probability scores.

    If scores have already been computed today (by the 07:30 WAT cron),
    returns the cached rows from Supabase.

    If no scores exist yet (e.g. the cron hasn't run, or this is a weekend
    dry-run), triggers on-demand computation from the live /forecast/alerts
    data and stores results before returning.

    Response shape::

        {
            "computed_at": "2026-07-14",
            "lgas": [
                {
                    "lga_name": "Alimosho",
                    "risk_tier": "High",
                    "outbreak_probability": 0.612,
                    "inundation_area_km2": 2.4,
                    "breeding_lag_days": 10,
                    "outbreak_window_start": "2026-07-24",
                    "outbreak_window_end": "2026-07-31",
                    "alert_sent": false,
                    ...
                },
                ...
            ]
        }
    """
    from floodsight.db.supabase_client import get_lga_health_risk_today

    try:
        rows = get_lga_health_risk_today()
        if rows:
            return {
                "computed_at": rows[0].get("computed_at", date.today().isoformat()),
                "lgas": rows,
            }

        # On-demand fallback — compute now from live alert grid
        return _compute_and_store()

    except Exception as exc:
        log.error("GET /health/risk error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/risk/{lga_name}")
def get_health_risk_lga(lga_name: str):
    """
    Return today's outbreak probability for a single LGA.
    Triggers on-demand computation if no scores exist yet today.
    """
    from floodsight.db.supabase_client import get_lga_health_risk_today

    try:
        rows  = get_lga_health_risk_today()
        if not rows:
            result = _compute_and_store()
            rows   = result.get("lgas", [])

        match = [r for r in rows if r["lga_name"].lower() == lga_name.lower()]
        if not match:
            # LGA exists but scored below inundation threshold (no active flood)
            return {
                "lga_name":             lga_name,
                "risk_tier":            "Low",
                "outbreak_probability": 0.0,
                "note": "No significant flood inundation in this LGA today.",
            }
        return match[0]

    except Exception as exc:
        log.error("GET /health/risk/%s error: %s", lga_name, exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


def _compute_and_store() -> dict:
    """
    Fetch live alert grid, score LGAs, store in Supabase, return result dict.
    Called when today's scores are not yet in the DB.
    """
    from api.data_provider import get_grid_geojson
    from floodsight.health.engine import score_lgas
    from floodsight.db.supabase_client import upsert_lga_health_risk

    geojson, _ = get_grid_geojson()

    # Compute live alert levels IN-PROCESS by calling the same function that
    # backs GET /forecast/alerts.
    #
    # This previously issued an HTTP request to os.getenv("RENDER_EXTERNAL_URL").
    # That secret is not set on this deployment, so render_url was always ""
    # and every request silently fell through to _compute_alert_levels_inline().
    # That fallback reads rain_24h_mm / rain_72h_mm off the static grid, which
    # does not carry rainfall columns, so it scored every cell with 0 mm ->
    # "No Alert" for all 24,933 cells -> score_lgas() found zero inundated
    # cells -> the health layer rendered empty even while the main FloodSight
    # map showed Watch/Warning. Calling the function directly removes the
    # env-var dependency, the self-HTTP round trip, and the cold-start race.
    try:
        from api.routers.forecast import get_grid_alerts

        alert_data   = get_grid_alerts()
        alert_levels = alert_data.get("alert_levels", [])
        if not alert_levels:
            raise ValueError("forecast returned no alert_levels")
    except Exception as exc:
        log.warning(
            "In-process forecast alert computation failed (%s) — "
            "falling back to inline estimate (rainfall-blind, low accuracy)",
            exc,
        )
        alert_levels = _compute_alert_levels_inline(geojson)

    event_id = date.today().isoformat()
    scores   = score_lgas(geojson, alert_levels, flood_event_id=event_id)
    inserted = upsert_lga_health_risk(scores)

    return {
        "computed_at": event_id,
        "lgas": inserted or scores,
    }


def _compute_alert_levels_inline(geojson: dict) -> list[str]:
    """
    Compute alert levels for each grid cell using the existing alert engine.
    Fallback when /forecast/alerts is unavailable (local dev, cold start race).
    Uses last-known rainfall — accuracy is lower than the full forecast stack.
    """
    from floodsight.alerts.engine import compute_alert_level
    from api.data_provider import get_grid

    gdf, _ = get_grid()
    levels  = []
    n       = len(geojson.get("features", []))

    for i in range(min(n, len(gdf))):
        rc  = gdf["risk_class"].iloc[i]
        r24 = float(gdf.get("rain_24h_mm", gdf).iloc[i]) if "rain_24h_mm" in gdf.columns else 0.0
        r72 = float(gdf.get("rain_72h_mm", gdf).iloc[i]) if "rain_72h_mm" in gdf.columns else 0.0
        levels.append(compute_alert_level(rc, r24, r72))

    return levels


# ---------------------------------------------------------------------------
# /health/chew-response  —  Africa's Talking inbound SMS webhook
# ---------------------------------------------------------------------------

class ChewResponsePayload(BaseModel):
    """
    Africa's Talking POST payload for inbound SMS.
    AT sends form-encoded data; FastAPI will parse it from JSON body too.
    """
    from_: str | None = None   # "from" is a Python keyword; AT sends as "from"
    text: str = ""
    to: str | None = None
    date: str | None = None

    class Config:
        # Allow "from" as a field alias
        populate_by_name = True
        fields = {"from_": "from"}


@router.post("/chew-response")
async def receive_chew_response(request: Request):
    """
    Africa's Talking inbound SMS webhook for CHEW replies.

    AT sends form-encoded POST data with fields:
        from, to, text, date, id, linkId (optional)

    Register this URL in the Africa's Talking dashboard:
        SMS → Inbox → Callback URL → https://<render-url>/health/chew-response

    Parsing logic
    -------------
    CONFIRM           → CHEW confirms receipt and will act
    REPORT <N>        → CHEW reports N malaria cases seen this week
    REPORT            → CHEW confirms cases but no count given
    HELP              → CHEW requests a callback
    anything else     → logged as UNKNOWN for manual review
    """
    from floodsight.db.supabase_client import record_chew_response

    # AT sends form-encoded — parse raw body to handle both form and JSON
    content_type = request.headers.get("content-type", "")
    if "form" in content_type:
        form_data = await request.form()
        phone     = form_data.get("from", "")
        raw_text  = form_data.get("text", "")
    else:
        body_json = await request.json()
        phone     = body_json.get("from", body_json.get("from_", ""))
        raw_text  = body_json.get("text", "")

    if not phone:
        raise HTTPException(status_code=400, detail="Missing 'from' field")

    normalized  = raw_text.strip().upper()
    parsed_action  = "UNKNOWN"
    cases_reported = None

    if normalized.startswith("CONFIRM"):
        parsed_action = "CONFIRM"
    elif normalized.startswith("REPORT"):
        parsed_action = "REPORT"
        parts = normalized.split()
        if len(parts) >= 2 and parts[1].isdigit():
            cases_reported = int(parts[1])
    elif normalized.startswith("HELP"):
        parsed_action = "HELP"

    record_chew_response(
        phone=phone,
        raw_message=raw_text,
        parsed_action=parsed_action,
        cases_reported=cases_reported,
        lga_name=None,   # resolved from phone inside record_chew_response
    )

    log.info(
        "CHEW response received: %s → %s (cases=%s)",
        phone, parsed_action, cases_reported,
    )
    return {"status": "received", "parsed_action": parsed_action}


# ---------------------------------------------------------------------------
# /health/mel/summary  —  MEL statistics for the health dashboard
# ---------------------------------------------------------------------------

@router.get("/mel/summary")
def get_mel_summary():
    """
    Return aggregated MEL statistics for the health dashboard KPI cards.

    Response::

        {
            "total_alerts_sent": 142,
            "chew_confirm_rate": 0.71,
            "mel_events_logged": 18,
            "nets_distributed": 1200,
            "rdt_kits_prepositioned": 80
        }
    """
    from floodsight.db.supabase_client import _get_client

    try:
        client = _get_client()

        alerts_count = (
            client.table("health_alerts")
            .select("id", count="exact")
            .execute()
            .count
        ) or 0

        confirm_count = (
            client.table("chew_responses")
            .select("id", count="exact")
            .eq("parsed_action", "CONFIRM")
            .execute()
            .count
        ) or 0

        mel_events_count = (
            client.table("mel_events")
            .select("id", count="exact")
            .execute()
            .count
        ) or 0

        mel_rows = (
            client.table("mel_events")
            .select("event_type,quantity")
            .execute()
        ).data or []

        nets_total = sum(r.get("quantity") or 0 for r in mel_rows if r.get("event_type") == "NETS_DISTRIBUTED")
        rdt_total  = sum(r.get("quantity") or 0 for r in mel_rows if r.get("event_type") == "RDT_KITS_PREPOSITIONED")

        return {
            "total_alerts_sent":       alerts_count,
            "chew_confirm_rate":       round(confirm_count / max(alerts_count, 1), 3),
            "mel_events_logged":       mel_events_count,
            "nets_distributed":        nets_total,
            "rdt_kits_prepositioned":  rdt_total,
        }

    except Exception as exc:
        log.error("GET /health/mel/summary error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ---------------------------------------------------------------------------
# /health/mel/operational  —  the PRIMARY PoC outcome indicators
# ---------------------------------------------------------------------------

@router.get("/mel/operational")
def get_operational_outcomes():
    """
    Return the PoC's PRIMARY (operational / intermediary) outcome indicators:
    alert acknowledgement rate, alert-to-action time, anticipatory-action
    rate, and entomological (Anopheles vs Culex) confirmation rate.

    These are the metrics the NEXA proof of concept is judged on. DHIS2
    case-counts are an exploratory secondary signal only (see /health/mel/summary
    and floodsight/health/mel.py for the rationale).

    Returns 0 / None-valued fields (not an error) before enrolment, so the
    dashboard renders from day one.
    """
    from floodsight.health.mel import get_operational_kpis

    try:
        return get_operational_kpis()
    except Exception as exc:
        log.error("GET /health/mel/operational error: %s", exc)
        raise HTTPException(status_code=500, detail=str(exc)) from exc
