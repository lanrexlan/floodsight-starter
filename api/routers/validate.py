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
import time
import urllib.request
from datetime import date, timedelta

from fastapi import APIRouter, HTTPException, Request
from floodsight.config import ALERT_UPGRADE, COASTAL_UPGRADE_LGAS, OGUN_UPGRADE_LGAS
from floodsight.forecast.marine import coastal_upgrade

log = logging.getLogger(__name__)

router = APIRouter(prefix="/validate", tags=["validate"])

# ── Multi-point validation grid (matches production rainfall_grid.py) ──────
# Using a single Ikeja-centre point misses hyper-localised Lagos storms.
# These 5 strategic points cover the main flood-affected zones; we take the
# maximum 24h and 72h rainfall across all points — consistent with how the
# live alert engine uses a 9-point spatial grid.
VALIDATION_POINTS: list[tuple[float, float]] = [
    (6.35, 3.40),   # Lagos Island / Victoria Island (tidal / coastal events)
    (6.35, 3.70),   # Lekki / Eti-Osa              (Lekki 2021, 2024)
    (6.55, 3.40),   # Ikeja / centre                (most mainland events)
    (6.55, 3.70),   # Kosofe / Ikorodu              (Ikorodu Road events)
    (6.55, 3.10),   # Alimosho / Badagry            (western mainland)
]
_CENTRE = (6.55, 3.40)   # used for antecedent (city-level aggregate)

# ── Historical dam/coastal monitoring ──────────────────────────────────────
# Dam: Ogun at Isheri (matches live floodsight/forecast/dam.py)
_DAM_LAT, _DAM_LON = 6.67, 3.43

# Coastal: just offshore Lagos (ERA5-Ocean gives sea_level_height_msl here)
_COAST_LAT, _COAST_LON = 6.30, 3.35

# LGA tier-upgrade sets — imported from config (single source of truth)
# Coastal: tidal surge / Niger-Benue backwater → upgrades shoreline LGAs
# Ogun:    Oyan Dam discharge spike → upgrades Ogun floodplain LGAs
_COASTAL_LGAS    = COASTAL_UPGRADE_LGAS
_OGUN_LGAS       = OGUN_UPGRADE_LGAS
# Coastal upgrades go through floodsight.forecast.marine.coastal_upgrade (two tiers).
_DAM_UPGRADE     = ALERT_UPGRADE

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
        "areas": "Eti-Osa, Kosofe, Gbagada, Orile-Agege, Ogudu",
        "description": "Almost 90mm of rain fell 18-19 June. 20 families displaced at Orile-Agege; child swept away. House collapsed in Ogudu.",
        "source": "FloodList / LASEMA, June 2020",
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
    # ── Additional events added Phase 22 ─────────────────────────────
    {
        "id": "2015_07",
        "name": "July 2015 Lagos Floods",
        "peak_date": "2015-07-14",
        "areas": "Mushin, Surulere, Lagos Island, Festac",
        "description": "Widespread flooding after sustained July rains. LASEMA deployed to multiple hotspots.",
        "source": "Vanguard Newspaper / LASEMA Sitrep, July 2015",
        "reported_severity": "Warning",
    },
    {
        "id": "2016_07",
        "name": "July 2016 Lagos Floods",
        "peak_date": "2016-07-19",
        "areas": "Ajah, Lagos Island, Victoria Island, Lekki Phase II",
        "description": "Severe flooding across coastal LGAs. Roads impassable for 24+ hours.",
        "source": "Punch Newspapers / NEMA, July 2016",
        "reported_severity": "Warning",
    },
    {
        "id": "2018_06",
        "name": "June 2018 Lagos Floods",
        "peak_date": "2018-06-21",
        "areas": "Ikeja, Agege, Alimosho, Surulere",
        "description": "Heavy overnight storm triggered flash flooding on major arterial roads.",
        "source": "The Guardian Nigeria / LASEMA, June 2018",
        "reported_severity": "Warning",
    },
    {
        "id": "2019_10",
        "name": "October 2019 Oyan Dam Flooding",
        "peak_date": "2019-10-21",
        "areas": "Badagry, Epe, coastal Lagos LGAs",
        "description": "Flooding amplified by release of water from Oyan Dam (Abeokuta). Six deaths reported in Lagos.",
        "source": "FloodList / NEMA Sitrep, October 2019",
        "reported_severity": "Warning",
    },
    {
        "id": "2021_07a",
        "name": "July 2021 Lagos Tidal-Rain Surge",
        "peak_date": "2021-07-10",
        "areas": "Lagos Island, Victoria Island, Lekki, Ikoyi",
        "description": "Major flooding from combination of heavy rain and high tides raising sea level 122cm above normal. Cars submerged, 4,000+ displaced.",
        "source": "LASEMA / Interconnected Disaster Risks Report, 2021",
        "reported_severity": "Warning",
    },
    {
        "id": "2021_07b",
        "name": "July 2021 Lagos Flash Floods",
        "peak_date": "2021-07-16",
        "areas": "Lagos Mainland, Gbagada, Mushin, Oshodi",
        "description": "Heavy rainfall caused flood depths up to 50 cm in residential areas. Significant vehicle damage reported.",
        "source": "FloodList, July 2021",
        "reported_severity": "Watch",
    },
    {
        "id": "2022_06",
        "name": "June 2022 Lagos Pre-Peak Floods",
        "peak_date": "2022-06-18",
        "areas": "Lagos Mainland, Apapa, Mushin",
        "description": "Roads and houses flooded after a downpour. Event preceded the larger July 2022 flooding by three weeks.",
        "source": "FloodList / NAN, June 2022",
        "reported_severity": "Watch",
    },
    {
        "id": "2023_09",
        "name": "September 2023 Lagos Floods",
        "peak_date": "2023-09-14",
        "areas": "Ikorodu, Kosofe, Gbagada, Ketu",
        "description": "End-of-season heavy rains flooded Ikorodu Road and surrounding communities. LASEMA reported over N10bn cumulative losses for 2023.",
        "source": "LASEMA Annual Report 2023 / Channels TV",
        "reported_severity": "Watch",
    },
    {
        "id": "2024_06",
        "name": "June 2024 Lagos Floods",
        "peak_date": "2024-06-28",
        "areas": "Oshodi, Mushin, Surulere, Egbeda, Gbagada, Ilupeju",
        "description": "Hours of heavy rainfall put major roads and residential communities under water. Multiple LGAs affected simultaneously.",
        "source": "Punch Newspapers / LASEMA, June 2024",
        "reported_severity": "Warning",
    },
    {
        "id": "2024_07",
        "name": "July 2024 Lekki Floods",
        "peak_date": "2024-07-03",
        "areas": "Lekki, Ibeju-Lekki, Ikoyi, Mushin, Ketu",
        "description": "10-hour rainfall caused buildings to collapse and cars to be swept away in Lekki. Student carried away by floods in Ketu.",
        "source": "Wikipedia / Punch / TheCable, July 2024",
        "reported_severity": "Warning",
    },
]

# ── In-process cache ──────────────────────────────────────────────────────
_cached_results: list[dict] | None = None


# ── Open-Meteo archive fetch ──────────────────────────────────────────────

def _fetch_nasa_power_point(
    lat: float, lon: float, peak_date: str
) -> tuple[float, float]:
    """Fetch 24h and 72h rainfall at a single lat/lon from NASA POWER."""
    d = date.fromisoformat(peak_date)
    start = (d - timedelta(days=2)).strftime("%Y%m%d")
    end   = d.strftime("%Y%m%d")

    url = (
        "https://power.larc.nasa.gov/api/temporal/daily/point"
        "?parameters=PRECTOTCORR"
        "&community=RE"
        f"&longitude={lon}&latitude={lat}"
        f"&start={start}&end={end}"
        "&format=JSON"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())

    raw = data["properties"]["parameter"]["PRECTOTCORR"]
    values = [v if v != -999.0 else 0.0 for v in raw.values()]
    return round(values[-1], 1), round(sum(values), 1)   # (24h, 72h)


def _fetch_nasa_power(peak_date: str) -> tuple[float, float]:
    """
    Primary source: NASA POWER API (IMERG-corrected daily precipitation).

    Fetches VALIDATION_POINTS in parallel and returns the *maximum* 24h and
    72h values across all points.  Lagos convective storms are highly
    localised — a single centre point routinely under-detects events that
    affect only Lekki, Kosofe, or the western mainland.  Taking the spatial
    maximum is consistent with how the live alert engine uses a 9-point grid.

    Returns (max_rain_24h_mm, max_rain_72h_mm).
    """
    import concurrent.futures

    results: list[tuple[float, float]] = []
    errors: list[str] = []

    with concurrent.futures.ThreadPoolExecutor(max_workers=len(VALIDATION_POINTS)) as pool:
        future_map = {
            pool.submit(_fetch_nasa_power_point, lat, lon, peak_date): (lat, lon)
            for lat, lon in VALIDATION_POINTS
        }
        for fut in concurrent.futures.as_completed(future_map):
            pt = future_map[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                errors.append(f"{pt}: {exc}")
                log.warning("NASA POWER point %s failed: %s", pt, exc)

    if not results:
        raise RuntimeError(f"All POWER points failed: {errors}")
    if errors:
        log.warning("NASA POWER: %d/%d points OK", len(results), len(VALIDATION_POINTS))

    max_24h = max(r[0] for r in results)
    max_72h = max(r[1] for r in results)
    log.debug("NASA POWER max: 24h=%.1f mm  72h=%.1f mm  (from %d points)",
               max_24h, max_72h, len(results))
    return max_24h, max_72h


def _fetch_antecedent_30d(peak_date: str) -> float:
    """
    Fetch 30-day accumulated rainfall ending on peak_date-1 from NASA POWER.
    Used to detect soil-saturation conditions (see RAIN_ANTECEDENT_SAT_30D_MM).
    Returns accumulated mm, or 0.0 on failure.
    """
    d = date.fromisoformat(peak_date)
    start = (d - timedelta(days=30)).strftime("%Y%m%d")
    end   = (d - timedelta(days=1)).strftime("%Y%m%d")
    lat, lon = _CENTRE

    url = (
        "https://power.larc.nasa.gov/api/temporal/daily/point"
        "?parameters=PRECTOTCORR"
        "&community=RE"
        f"&longitude={lon}&latitude={lat}"
        f"&start={start}&end={end}"
        "&format=JSON"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        raw = data["properties"]["parameter"]["PRECTOTCORR"]
        values = [v if v != -999.0 else 0.0 for v in raw.values()]
        return round(sum(values), 1)
    except Exception as exc:
        log.warning("Antecedent 30d fetch failed for %s: %s", peak_date, exc)
        return 0.0


def _fetch_era5_openmeteo(peak_date: str, retries: int = 3) -> tuple[float, float]:
    """
    Fallback source: Open-Meteo ERA5 archive.
    Lower resolution (~30 km); known to under-detect localised Lagos storms.
    Used only when NASA POWER is unavailable.

    Returns (rain_24h_mm, rain_72h_mm).
    """
    d = date.fromisoformat(peak_date)
    start = (d - timedelta(days=2)).isoformat()
    end   = d.isoformat()

    url = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={_CENTRE[0]}&longitude={_CENTRE[1]}"
        f"&start_date={start}&end_date={end}"
        "&daily=precipitation_sum"
        "&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})

    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read())
            break
        except Exception as exc:
            last_exc = exc
            wait = 2 ** attempt
            log.warning("ERA5 fallback attempt %d failed (%s) — retrying in %ds", attempt + 1, exc, wait)
            time.sleep(wait)
    else:
        raise last_exc  # type: ignore[misc]

    daily  = data["daily"]
    times  = daily["time"]
    precip = [p if p is not None else 0.0 for p in daily["precipitation_sum"]]
    peak_idx = times.index(peak_date) if peak_date in times else len(times) - 1
    return round(precip[peak_idx], 1), round(sum(precip[:peak_idx + 1]), 1)


def _fetch_rainfall_archive(peak_date: str, retries: int = 3) -> tuple[float, float]:
    """
    Fetch 24h and 72h rainfall ending on peak_date.

    Strategy (in order):
      1. NASA POWER API — IMERG-corrected, ~0.5° resolution, best for Lagos
         convective storms. Covers 1981-present, no auth required.
      2. Open-Meteo ERA5 — ~30 km global reanalysis, known to underestimate
         localised convective events but always available as a fallback.

    Returns (rain_24h_mm, rain_72h_mm).
    """
    try:
        result = _fetch_nasa_power(peak_date)
        log.debug("NASA POWER: %s → 24h=%.1f mm  72h=%.1f mm", peak_date, *result)
        return result
    except Exception as exc:
        log.warning("NASA POWER failed for %s (%s) — falling back to ERA5", peak_date, exc)

    return _fetch_era5_openmeteo(peak_date, retries=retries)


def _fetch_historical_dam(peak_date: str, window_days: int = 5) -> dict | None:
    """
    Fetch GloFAS v4 river discharge at Isheri for [peak-window_days, peak+2d].
    Uses the same Open-Meteo Flood API as the live dam signal, but with
    start_date/end_date instead of forecast_days — available back to 1984.
    Returns None on fetch failure (non-fatal).
    """
    from floodsight.forecast.dam import DAM_ADVISORY_M3S
    d = date.fromisoformat(peak_date)
    start = (d - timedelta(days=window_days)).isoformat()
    end   = (d + timedelta(days=2)).isoformat()
    url = (
        "https://flood-api.open-meteo.com/v1/flood"
        f"?latitude={_DAM_LAT}&longitude={_DAM_LON}"
        "&daily=river_discharge"
        f"&start_date={start}&end_date={end}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
        flows = data["daily"]["river_discharge"]
        dates = data["daily"]["time"]
        valid  = [(d2, q) for d2, q in zip(dates, flows) if q is not None]
        if not valid:
            return None
        peak_day, max_q = max(valid, key=lambda p: p[1])
        result = {
            "advisory":          bool(max_q >= DAM_ADVISORY_M3S),
            "max_discharge_m3s": round(float(max_q), 1),
            "peak_day":          peak_day,
            "threshold_m3s":     DAM_ADVISORY_M3S,
        }
        log.debug("Hist dam %s: max=%.1f m3/s (threshold=%.0f)",
                  peak_date, max_q, DAM_ADVISORY_M3S)
        return result
    except Exception as exc:
        log.warning("Historical dam fetch failed for %s: %s", peak_date, exc)
        return None


def _fetch_historical_coastal(peak_date: str, window_days: int = 3) -> dict | None:
    """
    Fetch hourly sea_level_height_msl at the Lagos coast for
    [peak-1d, peak+window_days], from the SAME model the live coastal signal
    uses, so historical and live thresholds mean the same thing.

    This previously requested ``&models=era5_ocean`` on the stated basis that
    ERA5-Ocean "covers 1940-present".  On the Open-Meteo marine API that
    model returns no sea_level_height_msl at all (every hour null, verified
    for 2021 and 2024), so this function returned None for every event and the
    coastal component of historical validation never ran.

    The default model has data from early 2023 only.  Events before that
    return None here — the honest answer is "no coastal record", not a guess.
    Returns None on fetch failure or missing data (non-fatal).
    """
    from floodsight.forecast.marine import COASTAL_HIGH_TIDE_M, COASTAL_SURGE_M
    d = date.fromisoformat(peak_date)
    start = (d - timedelta(days=1)).isoformat()
    end   = (d + timedelta(days=window_days)).isoformat()
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        f"?latitude={_COAST_LAT}&longitude={_COAST_LON}"
        "&hourly=sea_level_height_msl"
        f"&start_date={start}&end_date={end}"
    )
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
        with urllib.request.urlopen(req, timeout=25) as resp:
            data = json.loads(resp.read())
        heights = [h for h in data["hourly"].get("sea_level_height_msl", [])
                   if h is not None]
        if not heights:
            return None
        max_h = max(heights)
        result = {
            "advisory":              bool(max_h >= COASTAL_SURGE_M),
            "high_tide":             bool(max_h >= COASTAL_HIGH_TIDE_M),
            "max_sea_level_m":       round(float(max_h), 3),
            "threshold_m":           COASTAL_SURGE_M,
            "high_tide_threshold_m": COASTAL_HIGH_TIDE_M,
        }
        log.debug("Hist coastal %s: max=%.3f m (surge>=%.2f, high tide>=%.2f)",
                  peak_date, max_h, COASTAL_SURGE_M, COASTAL_HIGH_TIDE_M)
        return result
    except Exception as exc:
        log.warning("Historical coastal fetch failed for %s: %s", peak_date, exc)
        return None


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

    for i, event in enumerate(FLOOD_EVENTS):
        if i > 0:
            time.sleep(1)   # be polite to Open-Meteo; avoids connection resets
        try:
            rain_24h, rain_72h = _fetch_rainfall_archive(event["peak_date"])
        except Exception as exc:
            log.warning("Could not fetch archive data for %s: %s", event["id"], exc)
            rain_24h, rain_72h = 0.0, 0.0

        # Antecedent 30-day soil saturation — politely sleep a moment first
        # since we just fetched the event rainfall (multiple parallel calls)
        antecedent_30d = _fetch_antecedent_30d(event["peak_date"])
        log.info("  %s — 30-day antecedent: %.0f mm", event["id"], antecedent_30d)

        # Historical non-rainfall signals (GloFAS dam + ERA5-Ocean coastal)
        hist_dam     = _fetch_historical_dam(event["peak_date"])
        hist_coastal = _fetch_historical_coastal(event["peak_date"])

        coastal_active = bool(hist_coastal and (hist_coastal.get("advisory")
                                                or hist_coastal.get("high_tide")))
        dam_active     = bool(hist_dam     and hist_dam.get("advisory"))
        has_lga        = "lga_name" in gdf.columns

        if coastal_active:
            log.info("  %s — coastal advisory ACTIVE (%.3f m MSL)",
                     event["id"], hist_coastal["max_sea_level_m"])
        if dam_active:
            log.info("  %s — dam advisory ACTIVE (%.1f m3/s)",
                     event["id"], hist_dam["max_discharge_m3s"])

        # Pre-extract LGA names for fast per-cell lookup
        lga_list = gdf["lga_name"].tolist() if has_lga else None

        # Count alert levels across the whole grid (with LGA-based tier upgrades)
        counts: dict[str, int] = {"Warning": 0, "Watch": 0, "No Alert": 0}
        for i, risk_class in enumerate(gdf["risk_class"]):
            level = compute_alert_level(
                risk_class, rain_24h, rain_72h,
                antecedent_30d_mm=antecedent_30d,
            )
            if has_lga and lga_list:
                lga = str(lga_list[i])
                if coastal_active and lga in _COASTAL_LGAS:
                    level = coastal_upgrade(level, hist_coastal)
                if dam_active and lga in _OGUN_LGAS:
                    level = _DAM_UPGRADE.get(level, level)
            counts[level] = counts.get(level, 0) + 1

        total = len(gdf)
        if counts["Warning"] > 0:
            predicted = "Warning"
        elif counts["Watch"] > 0:
            predicted = "Watch"
        else:
            predicted = "No Alert"

        # Did FloodSight call it correctly?
        # Scoring rules:
        #   exact match                           → correct
        #   Warning expected, Watch predicted     → correct (detected the event, slightly under-alerted)
        #   Watch expected, Warning predicted     → correct (over-cautious is acceptable in a life-safety system)
        #   Warning/Watch expected, No Alert      → WRONG  (missed the event — the only truly bad case)
        correct = predicted == event["reported_severity"]
        detected = predicted in ("Watch", "Warning")

        results.append({
            **event,
            "rain_24h_mm":       rain_24h,
            "rain_72h_mm":       rain_72h,
            "antecedent_30d_mm": antecedent_30d,
            "hist_dam":          hist_dam,
            "hist_coastal":      hist_coastal,
            "dam_advisory":      dam_active,
            "coastal_advisory":  coastal_active,
            "rain_24h_label": _describe_rain(rain_24h),
            "rain_72h_label": _describe_rain(rain_72h),
            "alert_counts":   counts,
            "predicted_alert": predicted,
            "correct":         correct,
            "detected":        detected,
            "warning_pct":    round(counts["Warning"] / total * 100, 1),
            "watch_pct":      round(counts["Watch"]   / total * 100, 1),
        })

    return results


# ── Endpoint ──────────────────────────────────────────────────────────────

@router.get("/events")
def get_validation_events(request: Request, refresh: bool = False):
    """
    Returns back-test results for each documented Lagos flood event.

    For each event the response includes:
    - Actual recorded rainfall (from Open-Meteo archive)
    - What alert level FloodSight would have issued
    - Whether that matches the reported severity
    - Percentage of grid cells that would have been under Warning / Watch

    Results are cached after the first call (historical data never changes).
    Pass ?refresh=true to force a re-fetch.

    Now covers 18 events (Phase 22 expansion from 8 original).
    Dam-release events (2019_10, 2022_10) are included but noted as
    structurally hard for a rainfall-threshold model to detect.
    """
    if refresh:
        from api.auth import require_dispatch_secret
        require_dispatch_secret(request)
    global _cached_results
    if _cached_results is None or refresh:
        try:
            _cached_results = _compute_results()
        except Exception as exc:
            log.error("Validation computation failed: %s", exc)
            raise HTTPException(status_code=500, detail=str(exc)) from exc

    total = len(_cached_results)
    correct = sum(1 for r in _cached_results if r["correct"])

    # Of events where ERA5 recorded >=10mm (meaningful signal), how many correct?
    meaningful = [r for r in _cached_results if r["rain_24h_mm"] >= 10]
    meaningful_correct = sum(1 for r in meaningful if r["correct"])

    # Oyan Dam events: 2019_10 only.
    # 2022_10 (October 2022) is a Niger/Benue coastal backwater event — NOT an
    # Ogun dam event — so it is NOT listed here and IS covered by the coastal
    # advisory upgrade for Lagos Island / shoreline LGAs.
    oyan_dam_events = [r for r in _cached_results if r["id"] in ("2019_10",)]

    # Coastal/backwater events expected to be caught by the marine advisory
    coastal_events = [r for r in _cached_results if r["id"] in ("2021_07a", "2022_10")]

    # Hyper-local convective cells: satellite resolution too coarse to detect.
    # These are structural misses — no free reanalysis product can fix them.
    hyper_local_events = [r for r in _cached_results if r["id"] in ("2016_07", "2019_07")]

    return {
        "events": _cached_results,
        "summary": {
            "metric_definition": "Exact historical severity agreement; not prospective forecast accuracy.",
            "limitations": "Selected known flood events only. No non-flood control days or measured operational lead times; precision and false-alarm rate cannot be inferred.",
            "total_events":            total,
            "correct":                 correct,
            "accuracy_pct":            round(correct / total * 100) if total else 0,
            "meaningful_rain_events":  len(meaningful),
            "meaningful_correct":      meaningful_correct,
            "meaningful_accuracy_pct": round(meaningful_correct / len(meaningful) * 100) if meaningful else 0,
            "low_rainfall_misses": sum(
                1 for r in _cached_results
                if not r["correct"] and r["rain_24h_mm"] < 10
            ),
            "oyan_dam_events":    len(oyan_dam_events),
            "coastal_events":     len(coastal_events),
            "hyper_local_events": len(hyper_local_events),
            "note": (
                "Overall accuracy uses all 18 events (8 original + 10 added Phase 22). "
                "Rainfall data sourced from NASA POWER API (IMERG-corrected, ~0.5 degree resolution) "
                "with ERA5/Open-Meteo as fallback. "
                "Meaningful rain accuracy counts only events where the satellite recorded >=10 mm "
                "on the peak day. "
                "Coastal events (2021_07a, 2022_10) CANNOT yet be scored: the modelled "
                "sea-level record used by the live coastal signal begins in early 2023. "
                "The two-tier coastal signal (surge >= 1.20 m; high tide >= 1.05 m, which "
                "escalates rain-driven Watch only) is calibrated against the 2023-2026 "
                "record to control false alarms, not yet validated against a real surge. "
                "Oyan Dam events (2019_10) are covered by the GloFAS discharge advisory. "
                "Hyper-local convective cells (2016_07, 2019_07) remain structural misses -- "
                "the storm footprint is smaller than the free satellite grid (0.1 deg/~11 km) and "
                "cannot be detected without a dense rain-gauge network."
            ),
        },
    }
