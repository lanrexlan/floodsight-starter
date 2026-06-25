"""
GET /validate/events — back-test FloodSight alert logic against documented
                       Lagos flood events using real historical rainfall data
                       from the Open-Meteo archive API.

Results are computed once on first request and cached in-process for the
lifetime of the server (historical data never changes, so no TTL needed).

No API key required — Open-Meteo archive is free and open.
"""

from __future__ import annotations

import json
import logging
import urllib.request
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException

log = logging.getLogger(__name__)

router = APIRouter(prefix="/validate", tags=["validate"])

# ── Pilot grid centre (used for all Open-Meteo archive queries) ────────────
# Lagos is small enough that a single grid point represents the whole city.
LAGOS_LAT = 6.5244
LAGOS_LON = 3.3792

# ── Documented Lagos flood events ─────────────────────────────────────────
# Each entry is a confirmed flood event with a cited source.
# "peak_date" is the day of peak flooding (or first day of a multi-day event).
# We use the 24h total on peak_date and the 72h sum ending on peak_date.
FLOOD_EVENTS: list[dict] = [
    {
        "id": "2011_07",
        "name": "July 2011 Lagos Floods",
        "peak_date": "2011-07-10",
        "areas": "Ojo, Alimosho, Badagry, Kosofe",
        "description": "Severe flooding across multiple mainland LGAs. NEMA reported thousands displaced.",
        "source": "NEMA Lagos State Report, 2011",
        "reported_severity": "Warning",
    },
    {
        "id": "2012_07",
        "name": "July 2012 Lagos Floods",
        "peak_date": "2012-07-04",
        "areas": "Mushin, Agege, Ikeja, Lagos Island",
        "description": "Widespread flooding following sustained rainfall. Lagos State declared emergency in affected LGAs.",
        "source": "Lagos State Emergency Management Agency, 2012",
        "reported_severity": "Warning",
    },
    {
        "id": "2017_06",
        "name": "June 2017 Lagos Floods",
        "peak_date": "2017-06-22",
        "areas": "Surulere, Mushin, Lagos Island, Eti-Osa",
        "description": "Intense rainfall caused flooding on major roads and markets. Several deaths recorded.",
        "source": "Punch Newspapers / LASEMA, June 2017",
        "reported_severity": "Warning",
    },
    {
        "id": "2019_07",
        "name": "July 2019 Lagos Floods",
        "peak_date": "2019-07-08",
        "areas": "Lagos Island, Victoria Island, Lekki",
        "description": "Heavy overnight rain inundated low-lying communities and the Eko Bridge axis.",
        "source": "The Guardian Nigeria, July 2019",
        "reported_severity": "Warning",
    },
    {
        "id": "2020_06",
        "name": "June 2020 Lagos Floods",
        "peak_date": "2020-06-18",
        "areas": "Eti-Osa, Kosofe, Gbagada",
        "description": "Flooding in coastal areas of Eti-Osa and Kosofe following a long wet spell.",
        "source": "Vanguard Newspaper, June 2020",
        "reported_severity": "Warning",
    },
    {
        "id": "2022_07",
        "name": "July 2022 Lagos Floods",
        "peak_date": "2022-07-07",
        "areas": "Lagos Mainland, Apapa, Mushin",
        "description": "Major flooding following days of heavy rain. Critical roads impassable for 48 hours.",
        "source": "NAN / Lagos State Govt. Sitrep, July 2022",
        "reported_severity": "Warning",
    },
    {
        "id": "2022_10",
        "name": "October 2022 Dam-Release Flooding",
        "peak_date": "2022-10-12",
        "areas": "Lagos Island, Badagry, coastal areas",
        "description": "Flooding exacerbated by upstream dam releases on the Niger and Benue. Widespread coastal inundation.",
        "source": "Federal Ministry of Humanitarian Affairs, Oct 2022",
        "reported_severity": "Warning",
    },
    {
        "id": "2023_06",
        "name": "June 2023 Lagos Floods",
        "peak_date": "2023-06-20",
        "areas": "Kosofe, Gbagada, Ikorodu Road",
        "description": "Flash flooding on the Ikorodu Road corridor following an intense storm.",
        "source": "Channels TV, June 2023",
        "reported_severity": "Watch",
    },
]

# ── In-process cache ──────────────────────────────────────────────────────
_cached_results: list[dict] | None = None


# ── Open-Meteo archive fetch ──────────────────────────────────────────────

def _fetch_rainfall_archive(peak_date: str) -> tuple[float, float]:
    """
    Fetch daily precipitation for 3 days ending on peak_date.

    Returns (rain_24h_mm, rain_72h_mm).
    """
    d = date.fromisoformat(peak_date)
    start = (d - timedelta(days=2)).isoformat()  # 3-day window
    end   = d.isoformat()

    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LAGOS_LAT}&longitude={LAGOS_LON}"
        f"&start_date={start}&end_date={end}"
        "&daily=precipitation_sum"
        "&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
    with urllib.request.urlopen(req, timeout=20) as resp:
        data = json.loads(resp.read())

    daily = data["daily"]
    times  = daily["time"]
    precip = daily["precipitation_sum"]

    # Replace None values (missing data) with 0.0
    precip = [p if p is not None else 0.0 for p in precip]

    # 24h = peak day total; 72h = sum of all 3 days in window
    peak_idx  = times.index(peak_date) if peak_date in times else len(times) - 1
    rain_24h  = precip[peak_idx]
    rain_72h  = sum(precip[:peak_idx + 1])  # all days up to and including peak

    return round(rain_24h, 1), round(rain_72h, 1)


def _describe_rain(mm: float) -> str:
    if mm < 5:   return "Barely any rain"
    if mm < 20:  return "Light shower"
    if mm < 40:  return "Steady rain"
    if mm < 80:  return "Heavy downpour"
    if mm < 150: return "Very heavy rain"
    return "Extreme rainfall"


# ── Compute validation results ────────────────────────────────────────────

def _compute_results() -> list[dict]:
    from api.data_provider import get_grid
    from floodsight.alerts.engine import compute_alert_level

    gdf, _ = get_grid()
    results = []

    for event in FLOOD_EVENTS:
        try:
            rain_24h, rain_72h = _fetch_rainfall_archive(event["peak_date"])
        except Exception as exc:
            log.warning("Could not fetch archive data for %s: %s", event["id"], exc)
            rain_24h, rain_72h = 0.0, 0.0

        # Count alert levels across the whole grid
        counts: dict[str, int] = {"Warning": 0, "Watch": 0, "No Alert": 0}
        for risk_class in gdf["risk_class"]:
            level = compute_alert_level(risk_class, rain_24h, rain_72h)
            counts[level] = counts.get(level, 0) + 1

        total = len(gdf)
        if counts["Warning"] > 0:
            predicted = "Warning"
        elif counts["Watch"] > 0:
            predicted = "Watch"
        else:
            predicted = "No Alert"

        # Did FloodSight call it correctly?
        correct = (predicted == event["reported_severity"]) or (
            event["reported_severity"] == "Warning" and predicted in ("Warning", "Watch")
        )

        results.append({
            **event,
            "rain_24h_mm":    rain_24h,
            "rain_72h_mm":    rain_72h,
            "rain_24h_label": _describe_rain(rain_24h),
            "rain_72h_label": _describe_rain(rain_72h),
            "alert_counts":   counts,
            "predicted_alert": predicted,
            "correct":         correct,
            "warning_pct":    round(counts["Warning"] / total * 100, 1),
            "watch_pct":      round(counts["Watch"]   / total * 100, 1),
        })

    return results


# ── Endpoint ──────────────────────────────────────────────────────────────

@router.get("/events")
def get_validation_events(refresh: bool = False):
    """
    Returns back-test results for each documented Lagos flood event.

    For each event the response includes:
    - Actual recorded rainfall (from Open-Meteo archive)
    - What alert level FloodSight would have issued
    - Whether that matches the reported severity
    - Percentage of grid cells that would have been under Warning / Watch

    Results are cached after the first call (historical data never changes).
    Pass ?refresh=true to force a re-fetch.
    """
    global _cached_results
    if _cached_results is None or refresh:
        try:
            _cached_results = _compute_results()
        except Exception as exc:
            log.error("Validation computation failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    total = len(_cached_results)
    correct = sum(1 for r in _cached_results if r["correct"])

    return {
        "events": _cached_results,
        "summary": {
            "total_events":    total,
            "correct":         correct,
            "accuracy_pct":    round(correct / total * 100) if total else 0,
            "note": (
                "FloodSight is considered 'correct' if it issued Warning or Watch "
                "for a documented Warning event, and Warning for a Warning event."
            ),
        },
    }
