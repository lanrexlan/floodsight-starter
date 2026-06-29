"""
Phase 14: NASA GPM IMERG satellite observed rainfall.

Fetches the GPM IMERG Late Run daily accumulation for the Lagos AOI via
the earthaccess library, providing higher spatial accuracy than GFS analysis:

    IMERG Late Run  0.1° / ~11 km  ~14 h latency  ← used here
    GFS analysis    0.25° / ~28 km  ~6 h latency   ← fallback

Over Lagos (~90 km × 60 km) IMERG gives ~40 cells vs GFS's ~9 cells —
meaningful when a storm track hits Kosofe (north) but leaves Eti-Osa (south)
relatively dry.

Products
--------
GPM_3IMERGDL  Late Run daily  V07B — 0.1° global, mm/day accumulation
Yesterday's data is always available by 14:00 UTC (14-h latency).

HDF5 structure
--------------
  /Grid/lon               shape (3600,)      -179.95 .. 179.95, 0.1° steps
  /Grid/lat               shape (1800,)       -89.95 ..  89.95, 0.1° steps
  /Grid/precipitationCal  shape (1, 3600, 1800)  mm/day, fill = -9999.9
  Axis order: (time, lon, lat) — note lon before lat.

Auth
----
earthaccess reads EARTHDATA_USERNAME / EARTHDATA_PASSWORD from environment
(mirrored from NASA_EARTHDATA_* in config.py).

Caching
-------
Results are cached for 6 h in process memory — the daily product never
changes once published, so repeated calls within the same API pod are free.

Failure handling
----------------
Every exception path returns None.  Callers (rainfall_grid.py) fall back
to GFS-observed silently.  Nothing in this module can break the live API.
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta

log = logging.getLogger(__name__)

# In-process cache: cache_key → (expires_ts, {(lat, lon): mm})
_CACHE: dict[str, tuple[float, dict[tuple[float, float], float]]] = {}
_CACHE_TTL_S = 6 * 3600   # 6 hours — daily product is immutable once published


def fetch_imerg_daily(
    target_date: date | None = None,
    bbox: tuple[float, float, float, float] | None = None,
) -> dict[tuple[float, float], float] | None:
    """
    Fetch GPM IMERG Late Run daily accumulated rainfall for `target_date`.

    Parameters
    ----------
    target_date :
        Date to fetch (defaults to yesterday UTC).
    bbox :
        (lon_min, lat_min, lon_max, lat_max) — defaults to AOI_BBOX.

    Returns
    -------
    dict mapping (lat_centre, lon_centre) → mm/day at 0.1° resolution,
    or None if data is unavailable or any error occurs.
    """
    from floodsight.config import AOI_BBOX

    if bbox is None:
        bbox = AOI_BBOX
    if target_date is None:
        target_date = date.today() - timedelta(days=1)

    cache_key = f"{target_date}:{bbox}"
    now_ts = time.time()
    if cache_key in _CACHE:
        expires, data = _CACHE[cache_key]
        if now_ts < expires:
            log.debug("IMERG cache hit for %s", target_date)
            return data

    # Lazy imports — if earthaccess or h5py aren't installed, return None cleanly
    try:
        import earthaccess
        import h5py
        import numpy as np
    except ImportError as exc:
        log.warning("IMERG unavailable — missing dependency (%s). Falling back to GFS.", exc)
        return None

    # NASA Earthdata login (credentials from env, set by config.py on startup)
    try:
        auth = earthaccess.login(strategy="environment")
        if not getattr(auth, "authenticated", True):
            log.warning("NASA Earthdata auth failed — skipping IMERG")
            return None
    except Exception as exc:
        log.warning("NASA Earthdata login error: %s — skipping IMERG", exc)
        return None

    date_str = target_date.strftime("%Y-%m-%d")
    lon_min, lat_min, lon_max, lat_max = bbox

    try:
        log.info("IMERG: searching Late Run daily for %s, bbox=%s", date_str, bbox)
        results = earthaccess.search_data(
            short_name="GPM_3IMERGDL",
            temporal=(date_str, date_str),
            bounding_box=bbox,
        )
        if not results:
            log.info(
                "IMERG: no granule for %s (product may not be published yet; "
                "Late Run latency is ~14 h after day end)",
                date_str,
            )
            return None

        log.info("IMERG: opening %d granule(s) in-memory via earthaccess", len(results))
        files = earthaccess.open(results[:1])

        rainfall: dict[tuple[float, float], float] = {}

        with h5py.File(files[0]) as f:
            # Read coordinate arrays
            lons_all = f["Grid"]["lon"][:]       # shape (3600,)
            lats_all = f["Grid"]["lat"][:]       # shape (1800,)
            precip   = f["Grid"]["precipitationCal"][0]   # shape (3600, 1800)

            # Spatial subset — h5py fetches only the chunks that overlap bbox
            lon_mask = (lons_all >= lon_min) & (lons_all <= lon_max)
            lat_mask = (lats_all >= lat_min) & (lats_all <= lat_max)
            lon_idx  = np.where(lon_mask)[0]
            lat_idx  = np.where(lat_mask)[0]

            if len(lon_idx) == 0 or len(lat_idx) == 0:
                log.warning("IMERG: bbox subset is empty — check AOI_BBOX")
                return None

            # Read the rectangular slice (axis order: lon, lat)
            subset   = precip[lon_idx[0]: lon_idx[-1] + 1,
                              lat_idx[0]: lat_idx[-1] + 1]
            sub_lons = lons_all[lon_idx]
            sub_lats = lats_all[lat_idx]

            fill = -9000.0
            for loi, lon in enumerate(sub_lons):
                for li, lat in enumerate(sub_lats):
                    val = float(subset[loi, li])
                    if val > fill:
                        # Key is (lat, lon) — matches cKDTree ordering in rainfall_grid.py
                        rainfall[(round(float(lat), 2), round(float(lon), 2))] = val

        if not rainfall:
            log.warning("IMERG: subset contained no valid cells")
            return None

        _CACHE[cache_key] = (now_ts + _CACHE_TTL_S, rainfall)
        log.info(
            "IMERG %s: %d cells, range %.1f–%.1f mm",
            date_str, len(rainfall),
            min(rainfall.values()), max(rainfall.values()),
        )
        return rainfall

    except Exception as exc:
        log.warning("IMERG fetch error: %s — falling back to GFS analysis", exc)
        return None
