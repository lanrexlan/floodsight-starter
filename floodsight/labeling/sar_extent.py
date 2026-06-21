"""
Detect flood extent from Sentinel-1 SAR imagery for a historical event date,
as the first step in building labeled (terrain+rainfall -> depth) training
data (ROADMAP.md Phase 4). Pairs with floodsight/labeling/fwdet.py, which
turns the extent polygon this produces into a depth estimate.

Source: Sentinel-1 GRD, accessed via the Microsoft Planetary Computer STAC
API — free, no Earthdata-style account needed, query-and-stream rather
than bulk-download.
  https://planetarycomputer.microsoft.com/dataset/sentinel-1-rtc
  STAC API root: https://planetarycomputer.microsoft.com/api/stac/v1

Alternative sources if you need raw (non-RTC) GRD scenes or prefer ESA's
own catalogue:
  Copernicus Data Space Ecosystem (free account):
    https://dataspace.copernicus.eu/explore-data/data-collections/sentinel-data/sentinel-1
  Alaska Satellite Facility Vertex (free account, good for HyP3 RTC jobs):
    https://search.asf.alaska.edu/

Method: a before/after change-detection approach (the standard
quick-look method used in disaster response) —
  1. Pull a pre-event and a during/post-event Sentinel-1 VV scene.
  2. Threshold the VV backscatter (water is a strong specular reflector
     and appears very dark in VV) to get a water mask for each date.
  3. Flood extent = (during-event water mask) MINUS (pre-event water
     mask that was already permanent water, e.g. lagoon/creek).
This is deliberately simple (a documented, defensible starting point);
upgrading to a trained SAR classifier is a reasonable Phase 5+ task once
you have enough labeled events to evaluate one against.

Usage:
    python -m floodsight.labeling.sar_extent --pre 2024-09-01 --during 2024-09-10
"""

from __future__ import annotations

import logging
from datetime import datetime

import numpy as np

from floodsight.config import AOI_BBOX, RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

SAR_OUT_DIR = RAW_DIR / "sentinel1"
STAC_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
WATER_VV_THRESHOLD_DB = -17.0  # fallback only — see _otsu_threshold below.
# Calibration against the real Lagos Lagoon (June 2026) showed this fixed
# value is the wrong tool, not just a wrong number: known-water
# backscatter in real scenes is bimodal (a clean ~-16dB cluster of true
# calm water, plus a contaminating cluster near 0dB from harbor
# structures/boats inside the same OSM "water" polygon), and the exact
# split point shifts scene-to-scene with wind/processing conditions. A
# single hardcoded constant can't track that. _water_mask_from_item now
# computes an Otsu threshold fresh from each scene's own histogram by
# default; this constant remains only as an emergency fallback if Otsu
# produces something physically implausible (e.g. a degenerate
# near-unimodal scene).


def _otsu_threshold(values: np.ndarray, n_bins: int = 256) -> float:
    """Pure-numpy Otsu's method: finds the threshold that maximizes
    between-class variance of a histogram, i.e. the value that best
    splits a bimodal distribution into its two clusters. Standard
    approach for SAR water/land separation precisely because the
    absolute backscatter level isn't stable across scenes (wind, sensor
    geometry, processing) — only the existence of two clusters is.
    No extra dependency (skimage) needed for an algorithm this small."""
    finite = values[np.isfinite(values)]
    if len(finite) < n_bins:
        raise ValueError("Not enough valid pixels to compute a histogram-based threshold")

    hist, bin_edges = np.histogram(finite, bins=n_bins)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    weight_total = hist.sum()

    weight_below = np.cumsum(hist)
    weight_above = weight_total - weight_below

    # Avoid division by zero at the histogram's extreme edges
    with np.errstate(invalid="ignore", divide="ignore"):
        mean_below = np.cumsum(hist * bin_centers) / weight_below
        mean_above = (np.sum(hist * bin_centers) - np.cumsum(hist * bin_centers)) / weight_above

    with np.errstate(invalid="ignore", divide="ignore"):
        between_class_variance = weight_below * weight_above * (mean_below - mean_above) ** 2
    between_class_variance = np.nan_to_num(between_class_variance, nan=0.0)

    best_idx = int(np.argmax(between_class_variance))
    return float(bin_centers[best_idx])


def _search_scene(date: datetime, bbox: tuple[float, float, float, float], window_days: int = 8):
    """Find the closest Sentinel-1 RTC scene to `date` covering bbox,
    searching +/- window_days around the target rather than requiring an
    exact-day match. Sentinel-1's revisit cycle over a given point is
    NOT daily — with only Sentinel-1A operational (the case for most of
    2022-2024, after 1B failed and before 1C launched in Dec 2024), it's
    roughly 12 days. An exact-day search misses far more often than it
    hits; this widens the net and picks whichever pass is nearest the
    date you actually care about.

    Retries the search itself with increasing backoff: this call has
    been observed to fail with a server-side timeout multiple times in
    a row in practice (not just an occasional blip), so a single
    immediate retry often isn't enough — this waits real time between
    attempts (5s, 15s, 30s) rather than hammering the API again
    instantly, in case the issue is rate-limiting rather than a one-off
    hiccup.

    Requires: pip install pystac-client planetary-computer rioxarray"""
    import time

    import planetary_computer
    import pystac_client
    from datetime import timedelta
    from pystac_client.exceptions import APIError

    catalog = pystac_client.Client.open(STAC_API_URL, modifier=planetary_computer.sign_inplace)
    start = date - timedelta(days=window_days)
    end = date + timedelta(days=window_days)

    backoff_seconds = [5, 15, 30]
    items = None
    last_error = None
    for attempt, delay in enumerate([0] + backoff_seconds, start=1):
        if delay:
            log.warning(
                "Search attempt %d failed (%s) — waiting %ds before retrying...",
                attempt - 1, last_error, delay,
            )
            time.sleep(delay)
        try:
            search = catalog.search(
                collections=["sentinel-1-rtc"],
                bbox=bbox,
                datetime=f"{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}T23:59:59Z",
            )
            items = list(search.items())
            break
        except APIError as exc:
            last_error = exc
            continue
    else:
        pass

    if items is None:
        log.error(
            "Search failed after %d attempts (last error: %s). This many "
            "consecutive failures suggests something more persistent than "
            "normal flakiness — worth checking "
            "https://planetarycomputer.microsoft.com/ directly in a "
            "browser to see if the service is reporting issues, or simply "
            "waiting longer (minutes, not seconds) before trying again in "
            "case of rate-limiting.",
            len(backoff_seconds) + 1, last_error,
        )
        return None

    if not items:
        log.warning(
            "No Sentinel-1 scenes found within +/-%d days of %s either — "
            "try a larger window_days, or this AOI/period may genuinely "
            "have a coverage gap.",
            window_days, date.date(),
        )
        return None

    def _seconds_from_target(item) -> float:
        item_dt = datetime.fromisoformat(item.properties["datetime"].replace("Z", "+00:00"))
        return abs((item_dt.replace(tzinfo=None) - date).total_seconds())

    items.sort(key=_seconds_from_target)
    closest = items[0]
    log.info(
        "Found %d Sentinel-1 scene(s) within +/-%d days of %s — using "
        "closest acquisition: %s",
        len(items), window_days, date.date(), closest.properties["datetime"],
    )
    return closest


def _download_asset(href: str, cache_dir, local_filename: str) -> "Path":  # noqa: F821
    """Downloads a (already-signed) asset URL fully to a local cache file
    using plain requests, rather than letting GDAL/rioxarray stream
    individual tiles over HTTP on demand. This trades some speed for
    reliability: streaming reads of two different remote COGs in
    sequence within one process were failing consistently on the second
    file (with both a stale-token theory and a retry-config fix tried
    and ruled out in turn) — most likely a GDAL HTTP/connection-cache
    issue carrying bad state from the first file's connection into the
    second. Downloading fully sidesteps that whole class of bug: once
    the file is on disk, the actual raster read has zero network
    involvement.

    local_filename must be caller-supplied, not derived from the URL
    path: every Sentinel-1 RTC scene's VV asset lives at the same
    generic filename ("iw-vv.rtc.tiff") within its own item-specific
    folder — deriving the local cache name from just the URL's last path
    segment collided across different scenes, silently treating a
    different scene's download as "already cached" and using the wrong
    data entirely. Pass something derived from the STAC item's own
    unique ID instead (see _water_mask_from_item)."""
    from pathlib import Path

    import requests

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / local_filename

    if out_path.exists() and out_path.stat().st_size > 0:
        log.info("Already downloaded %s, using cached copy", local_filename)
        return out_path

    log.info("Downloading %s (full file, not streamed — this may take a moment)", local_filename)
    with requests.get(href, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        tmp_path = out_path.with_suffix(out_path.suffix + ".partial")
        with open(tmp_path, "wb") as f:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                f.write(chunk)
        tmp_path.rename(out_path)
    log.info("Saved %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)
    return out_path


def _water_mask_from_item(item, bbox: tuple[float, float, float, float] = AOI_BBOX) -> "xarray.DataArray":  # noqa: F821
    """Downloads the VV band fully (see _download_asset) then reads it
    from local disk — no network involved in the actual raster read, so
    none of the streaming-COG failure modes (partial tile reads, stale
    SAS tokens mid-read, GDAL connection-cache issues between
    sequential remote opens) can occur here.

    Clips to the AOI (with a buffer) immediately after reading, BEFORE
    computing the Otsu threshold or building the water mask. This
    matters for two reasons, not just one: a Sentinel-1 scene covers
    ~250km — vastly more area than a typical AOI — and (1) computing
    Otsu's threshold from the whole scene's histogram means it's
    calibrated against mostly-irrelevant land/water far from the AOI,
    not the area that actually matters, and (2) without this clip, SAR
    speckle noise (inherent pixel-level noise even over identical
    ground, present in any single-look SAR image) produces scattered
    false-positive "flood" pixels across the entire scene. The first
    real attempt at this exact event found 116,608 "flooded" cells
    spanning almost the full extent of a 111km DEM tile, with literally
    none of them inside the actual 3-LGA AOI — that's what motivated
    this fix; restricting to the AOI first eliminates the vast majority
    of that noise by construction, since we simply never look at the
    irrelevant area it was coming from.

    Returns a uint8 (not bool) 0/1 array with nodata explicitly cleared:
    GDAL has no native boolean raster type, and a raw boolean DataArray
    derived from the source SAR data inherits that source's nodata value
    (a large negative float sentinel) in its .rio metadata. Passing that
    inherited float nodata through to reproject_match() on a boolean
    array fails outright (can't represent -32768.0 as a bool). uint8
    with nodata cleared reprojects cleanly with nearest-neighbor
    resampling, which is also the dtype-correct choice for a categorical
    0/1 mask (same reasoning as the land cover resampling fix earlier in
    this project — never bilinear-interpolate categorical data)."""
    import planetary_computer
    import rioxarray

    vv_href = planetary_computer.sign(item.assets["vv"].href)
    local_filename = f"{item.id}_vv.tif"
    local_path = _download_asset(vv_href, SAR_OUT_DIR / "cache", local_filename)
    da = rioxarray.open_rasterio(local_path).squeeze().load()

    # Buffer the AOI bbox (~5km) so reproject_match later has margin to
    # work with even if the pre/during scenes have slightly different
    # footprints/orientations — clipping both to the exact same tight
    # box risks one of them coming up just short at an edge.
    buffer_deg = 0.05
    lon_min, lat_min, lon_max, lat_max = bbox
    buffered_bbox = (lon_min - buffer_deg, lat_min - buffer_deg, lon_max + buffer_deg, lat_max + buffer_deg)
    da = da.rio.clip_box(*buffered_bbox, crs="EPSG:4326")

    vv_db = 10 * np.log10(da.where(da > 0))
    vv_db_values = vv_db.to_numpy()

    try:
        threshold = _otsu_threshold(vv_db_values)
        if not (-30 < threshold < 5):
            # Sanity bound on the result itself, not just the input: a
            # genuinely degenerate/unimodal scene can make Otsu return
            # something physically nonsensical for SAR water detection.
            log.warning(
                "Otsu threshold (%.2f dB) outside the physically plausible "
                "range for SAR water — falling back to fixed default %.2f dB.",
                threshold, WATER_VV_THRESHOLD_DB,
            )
            threshold = WATER_VV_THRESHOLD_DB
        else:
            log.info("Otsu water threshold for this scene: %.2f dB", threshold)
    except ValueError:
        log.warning(
            "Could not compute an Otsu threshold for this scene (too few "
            "valid pixels) — falling back to fixed default %.2f dB.",
            WATER_VV_THRESHOLD_DB,
        )
        threshold = WATER_VV_THRESHOLD_DB

    water_mask = (vv_db < threshold).astype("uint8")
    water_mask = water_mask.rio.write_nodata(None)
    return water_mask


def detect_flood_extent(
    pre_event_date: datetime,
    during_event_date: datetime,
    bbox: tuple[float, float, float, float] = AOI_BBOX,
    window_days: int = 8,
):
    """Returns a boolean flood-extent raster (during-event water minus
    pre-existing permanent water)."""
    pre_item = _search_scene(pre_event_date, bbox, window_days=window_days)
    during_item = _search_scene(during_event_date, bbox, window_days=window_days)
    if pre_item is None or during_item is None:
        log.error(
            "Could not find both pre- and during-event scenes within "
            "+/-%d days; aborting. Try --window-days with a larger value.",
            window_days,
        )
        return None

    pre_water = _water_mask_from_item(pre_item)
    during_water = _water_mask_from_item(during_item)

    # Align grids in case of slightly different scene footprints/orbits
    during_water = during_water.rio.reproject_match(pre_water)

    # Explicit == comparisons, not bitwise &/~ on uint8: these arrays are
    # 0/1 uint8 (see _water_mask_from_item), and bitwise NOT on a uint8
    # 0 gives 255, not 1 — bitwise ops only behave like logical ops on
    # true bool dtypes, which reproject_match can't take directly (see
    # the nodata note above). Comparing == 1 / == 0 gets real booleans
    # back out for the logical combination, regardless of stored dtype.
    flood_extent = (during_water == 1) & (pre_water == 0)

    SAR_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SAR_OUT_DIR / f"flood_extent_{during_event_date.strftime('%Y%m%d')}.tif"
    flood_extent.astype("uint8").rio.to_raster(out_path)
    log.info("Saved flood extent mask to %s", out_path)
    return out_path


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--pre", required=True, help="Pre-event date YYYY-MM-DD")
    parser.add_argument("--during", required=True, help="During/post-event date YYYY-MM-DD")
    parser.add_argument(
        "--window-days", type=int, default=8,
        help="Search +/- this many days around each target date for the "
             "closest available Sentinel-1 scene (default: 8)",
    )
    args = parser.parse_args()
    detect_flood_extent(
        datetime.strptime(args.pre, "%Y-%m-%d"),
        datetime.strptime(args.during, "%Y-%m-%d"),
        window_days=args.window_days,
    )
