"""
NASA GPM IMERG satellite observed rainfall.

Phase 14:   IMERG Late Run daily (~14 h latency, yesterday's data).
Phase 18T2: Added IMERG Early Run (~4 h latency, yesterday).
            Try Early first → Late second → return None (fall back to GFS).

Products
--------
GPM_3IMERGDE  Early Run daily  0.1° (~11 km)  ~4 h latency after day end
GPM_3IMERGDL  Late Run  daily  0.1° (~11 km)  ~14 h latency after day end

Both cover a complete calendar day (UTC).  "Early" is the same accumulation
window as "Late" but published 10 hours sooner with fewer bias corrections.
For flood alerting purposes the extra 10 hours of availability matters more
than the marginal accuracy improvement of the Late product.

Over Lagos (~90 km × 60 km) IMERG gives ~40 cells vs GFS's ~9 cells —
meaningful when a storm track hits Kosofe (north) but leaves Eti-Osa
(south) relatively dry.

HDF5 structure (both products)
------------------------------
  /Grid/lon               shape (3600,)       -179.95 .. 179.95, 0.1° steps
  /Grid/lat               shape (1800,)        -89.95 ..  89.95, 0.1° steps
  /Grid/precipitationCal  shape (1, 3600, 1800) mm/day, fill = -9999.9
  Axis order: (time, lon, lat) — note lon before lat.

Auth
----
earthaccess reads EARTHDATA_USERNAME / EARTHDATA_PASSWORD from environment
(mirrored from NASA_EARTHDATA_* in config.py).

Caching
-------
Each (product, date) result is cached for 6 h in process memory — the daily
product is immutable once published.

Failure handling
----------------
Every exception path returns None.  Callers (rainfall_grid.py) silently fall
back to GFS-observed.  Nothing in this module can crash the live API.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import NamedTuple

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# IMERG product registry — tried in order, first success wins
# ---------------------------------------------------------------------------

class _ImergProduct(NamedTuple):
    short_name:  str    # NASA CMR short name
    run_label:   str    # human-readable label for logging
    latency_h:   int    # approximate latency in hours after day end


_PRODUCTS: list[_ImergProduct] = [
    _ImergProduct("GPM_3IMERGDE", "Early Run", 4),    # ~4 h latency — try first
    _ImergProduct("GPM_3IMERGDL", "Late Run",  14),   # ~14 h latency — fallback
]

# In-process cache: (short_name, date_str, bbox) → (expires_ts, data)
_CACHE: dict[str, tuple[float, dict[tuple[float, float], float]]] = {}
_CACHE_TTL_S = 6 * 3600


# ---------------------------------------------------------------------------
# Internal: fetch a single IMERG product
# ---------------------------------------------------------------------------

def _fetch_imerg_product(
    product: _ImergProduct,
    target_date: date,
    bbox: tuple[float, float, float, float],
) -> dict[tuple[float, float], float] | None:
    """
    Attempt to fetch one IMERG daily product for target_date.

    Returns
    -------
    dict mapping (lat, lon) → mm/day, or None on any failure.
    Failures are always silent — callers decide what to do next.
    """
    cache_key = f"{product.short_name}:{target_date}:{bbox}"
    now_ts = time.time()
    if cache_key in _CACHE:
        expires, data = _CACHE[cache_key]
        if now_ts < expires:
            log.debug("IMERG cache hit: %s %s", product.run_label, target_date)
            return data

    try:
        import earthaccess
        import h5py
        import numpy as np
    except ImportError as exc:
        log.warning("IMERG unavailable — missing dependency: %s", exc)
        return None

    try:
        auth = earthaccess.login(strategy="environment")
        if not getattr(auth, "authenticated", True):
            log.warning("NASA Earthdata auth failed — skipping IMERG")
            return None
    except Exception as exc:
        log.warning("NASA Earthdata login error: %s", exc)
        return None

    date_str = target_date.strftime("%Y-%m-%d")
    lon_min, lat_min, lon_max, lat_max = bbox

    try:
        log.info(
            "IMERG %s: searching %s for %s, bbox=%s",
            product.run_label, product.short_name, date_str, bbox,
        )
        results = earthaccess.search_data(
            short_name=product.short_name,
            temporal=(date_str, date_str),
            bounding_box=bbox,
        )
        if not results:
            log.info(
                "IMERG %s: no granule for %s (~%d h latency — may not be published yet)",
                product.run_label, date_str, product.latency_h,
            )
            return None

        log.info("IMERG %s: opening %d granule(s)", product.run_label, len(results))
        files = earthaccess.open(results[:1])

        rainfall: dict[tuple[float, float], float] = {}

        with h5py.File(files[0]) as f:
            lons_all = f["Grid"]["lon"][:]
            lats_all = f["Grid"]["lat"][:]
            precip   = f["Grid"]["precipitationCal"][0]   # shape (3600, 1800)

            lon_mask = (lons_all >= lon_min) & (lons_all <= lon_max)
            lat_mask = (lats_all >= lat_min) & (lats_all <= lat_max)
            lon_idx  = np.where(lon_mask)[0]
            lat_idx  = np.where(lat_mask)[0]

            if len(lon_idx) == 0 or len(lat_idx) == 0:
                log.warning("IMERG: bbox subset is empty — check AOI_BBOX")
                return None

            subset   = precip[lon_idx[0]: lon_idx[-1] + 1,
                              lat_idx[0]: lat_idx[-1] + 1]
            sub_lons = lons_all[lon_idx]
            sub_lats = lats_all[lat_idx]

            fill = -9000.0
            for loi, lon_v in enumerate(sub_lons):
                for li, lat_v in enumerate(sub_lats):
                    val = float(subset[loi, li])
                    if val > fill:
                        rainfall[(round(float(lat_v), 2), round(float(lon_v), 2))] = val

        if not rainfall:
            log.warning("IMERG %s: subset contained no valid cells", product.run_label)
            return None

        _CACHE[cache_key] = (now_ts + _CACHE_TTL_S, rainfall)
        log.info(
            "IMERG %s %s: %d cells, range %.1f–%.1f mm",
            product.run_label, date_str, len(rainfall),
            min(rainfall.values()), max(rainfall.values()),
        )
        return rainfall

    except Exception as exc:
        log.warning(
            "IMERG %s fetch error: %s — will try next product or fall back to GFS",
            product.run_label, exc,
        )
        return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_imerg_daily(
    target_date: date | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[tuple[float, float], float] | None:
    """
    Fetch GPM IMERG daily accumulated rainfall for `target_date`.

    Tries the Early Run product first (~4 h latency), then the Late Run
    (~14 h latency).  Returns the first successful result or None.

    Parameters
    ----------
    target_date :
        Date to fetch (defaults to yesterday UTC).
    bbox :
        (lon_min, lat_min, lon_max, lat_max) — defaults to AOI_BBOX.

    Returns
    -------
    dict mapping (lat_centre, lon_centre) → mm/day at 0.1° resolution,
    or None if both products are unavailable.
    """
    from floodsight.config import AOI_BBOX

    if bbox is None:
        bbox = AOI_BBOX
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    for product in _PRODUCTS:
        result = _fetch_imerg_product(product, target_date, bbox)
        if result is not None:
            log.info(
                "IMERG: using %s for %s (~%d h latency, %d cells)",
                product.run_label, target_date, product.latency_h, len(result),
            )
            # Attach metadata so callers can log which product was used
            result.__class__ = dict   # already a dict — ensure returned as plain dict
            return result

    log.info(
        "IMERG: no product available for %s — caller will fall back to GFS observed",
        target_date,
    )
    return None


def get_imerg_product_used(
    target_date: date | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> str:
    """
    Return a label for which IMERG product is currently cached for target_date.
    Used by rainfall_grid.py to populate observed_source metadata.

    Returns "IMERG_early", "IMERG_late", or "unavailable".
    """
    from floodsight.config import AOI_BBOX

    if bbox is None:
        bbox = AOI_BBOX
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    now_ts = time.time()
    for product in _PRODUCTS:
        cache_key = f"{product.short_name}:{target_date}:{bbox}"
        if cache_key in _CACHE:
            expires, data = _CACHE[cache_key]
            if now_ts < expires and data:
                return f"IMERG_{product.run_label.split()[0].lower()}"   # "IMERG_early" or "IMERG_late"

    return "unavailable"
