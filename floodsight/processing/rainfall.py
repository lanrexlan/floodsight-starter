"""
Sample CHIRPS daily rainfall rasters at the AOI to compute rain_24h_mm /
rain_72h_mm for a specific date — the rainfall features ml/dataset.py
needs to pair with a depth label (ROADMAP.md Phase 4), and eventually
what the alert engine should use instead of dashboard sliders once
Phase 2 (automated ingestion) is wired up.

CHIRPS's ~5.5km native resolution is far coarser than the 30m modelling
grid, so this returns a single AOI-wide average per day rather than a
per-cell value — appropriate at this resolution. A finer-resolution
source (GPM IMERG) would be needed for genuine per-cell rainfall
variation across a single LGA.

Usage:
    python -m floodsight.processing.rainfall --date 2024-07-03
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

from floodsight.config import AOI_BBOX, RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

CHIRPS_DIR = RAW_DIR / "rainfall" / "chirps"


def sample_chirps_day(date: datetime, bbox=AOI_BBOX) -> float | None:
    """Mean CHIRPS rainfall (mm) over the AOI bbox for one calendar day.
    Returns None if that day's file hasn't been downloaded yet."""
    import rasterio
    from rasterio.mask import mask
    from rasterio.warp import transform_bounds
    from shapely.geometry import box

    fname = f"chirps-v2.0.{date.year}.{date.month:02d}.{date.day:02d}.tif"
    path = CHIRPS_DIR / fname
    if not path.exists():
        log.warning("No CHIRPS file for %s at %s — download it first.", date.date(), path)
        return None

    with rasterio.open(path) as src:
        query_bbox = bbox
        if src.crs is not None and src.crs.to_epsg() != 4326:
            # CHIRPS is normally EPSG:4326, but don't assume blindly —
            # reproject the AOI bbox to match if it ever isn't.
            query_bbox = transform_bounds("EPSG:4326", src.crs, *bbox)
        aoi_geom = [box(*query_bbox)]

        out_image, _ = mask(src, aoi_geom, crop=True, nodata=src.nodata)
        data = out_image[0].astype(float)
        if src.nodata is not None:
            data = np.where(data == src.nodata, np.nan, data)
        valid = data[~np.isnan(data)]

    if len(valid) == 0:
        log.warning("No valid CHIRPS pixels within AOI for %s", date.date())
        return None

    return float(valid.mean())


def compute_rain_totals(event_date: datetime, window_72h_days: int = 3) -> dict:
    """
    rain_24h_mm: CHIRPS total for event_date's calendar day alone.
    rain_72h_mm: sum of event_date and the (window_72h_days - 1) days
    immediately before it (default: 3 full calendar days, ending on and
    including event_date). CHIRPS is daily-aggregated, not sub-daily, so
    this is necessarily an approximation of a true rolling 72-hour
    window — it's "the 3 calendar days up to and including the event,"
    not a precise hour-by-hour accumulation.
    """
    rain_24h = sample_chirps_day(event_date)

    totals_72h = []
    for i in range(window_72h_days):
        day = event_date - timedelta(days=i)
        val = sample_chirps_day(day)
        if val is not None:
            totals_72h.append(val)

    rain_72h = float(sum(totals_72h)) if totals_72h else None
    if totals_72h and len(totals_72h) < window_72h_days:
        log.warning(
            "Only %d of %d days available for the 72h window — rain_72h_mm "
            "is a partial sum, not a true 3-day total. Download the "
            "missing days for an accurate figure.",
            len(totals_72h), window_72h_days,
        )

    result = {
        "event_date": event_date.strftime("%Y-%m-%d"),
        "rain_24h_mm": round(rain_24h, 2) if rain_24h is not None else None,
        "rain_72h_mm": round(rain_72h, 2) if rain_72h is not None else None,
        "days_used_for_72h": len(totals_72h),
    }
    log.info("Rainfall totals for %s: %s", event_date.date(), result)
    return result


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--date", required=True,
        help="Event date YYYY-MM-DD (rain_24h = this day's total, "
             "rain_72h = this day + the 2 days immediately before it)",
    )
    args = parser.parse_args()
    compute_rain_totals(datetime.strptime(args.date, "%Y-%m-%d"))
