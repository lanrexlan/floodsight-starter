"""
Detect flood extent from Sentinel-1 SAR imagery for a historical event date,
as the first step in building labeled (terrain+rainfall -> depth) training
data (ROADMAP.md Phase 4). Pairs with floodsight/labeling/fwdet.py, which
turns the extent polygon this produces into a depth estimate.

Primary source: Element84 Earth Search v1 (public, no account needed)
  STAC API root: https://earth-search.aws.element84.com/v1
  Collection:    sentinel-1-grd
  Data:          Sentinel-1 GRD amplitude (uint16 DN) on public AWS S3

Fallback source: ASF + HyP3 on-demand RTC (NASA Earthdata credentials)
  Requires: NASA_EARTHDATA_USERNAME / NASA_EARTHDATA_PASSWORD in .env
  HyP3 produces radiometrically terrain-corrected (RTC) sigma0 tiffs —
  same format as the old Planetary Computer sentinel-1-rtc collection.
  HyP3 processing takes ~30-60 min per scene; scenes are cached locally
  so they are only processed once.

Note on Planetary Computer (original source, now retired):
  Microsoft retired the Planetary Computer STAC service in late 2024.
  The planetarycomputer.microsoft.com domain no longer resolves.

Method: a before/after change-detection approach —
  1. Pull a pre-event and a during/post-event Sentinel-1 VV scene.
  2. Threshold the VV backscatter (water appears very dark in VV) to get
     a water mask for each date.
  3. Flood extent = (during-event water mask) MINUS (pre-event water
     mask that was already permanent water, e.g. lagoon/creek).

Data format note: Element84 GRD provides raw DN amplitude (uint16).
  Converting to a log scale with 10*log10(DN) preserves the bimodal
  land/water contrast that Otsu needs — absolute calibration to sigma0
  is not required for relative change detection. The Otsu sanity check
  is calibrated against this DN-log range (15–50 dB), not the sigma0-dB
  range (-30–5 dB) that applies to pre-calibrated RTC products. Both
  branches feed the same Otsu + threshold logic; only the sanity bounds
  differ.

Usage:
    python -m floodsight.labeling.sar_extent --pre 2021-06-28 --during 2021-07-10
"""

from __future__ import annotations

import logging
import os
from datetime import datetime
from pathlib import Path

import numpy as np

from floodsight.config import AOI_BBOX, RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

SAR_OUT_DIR = RAW_DIR / "sentinel1"
STAC_ELEMENT84_URL = "https://earth-search.aws.element84.com/v1"
WATER_VV_THRESHOLD_DB = -17.0   # sigma0 dB fallback for RTC/HyP3 data
WATER_VV_THRESHOLD_DN_DB = 32.0 # 10*log10(DN) fallback for raw GRD data


def _otsu_threshold(values: np.ndarray, n_bins: int = 256) -> float:
    """Pure-numpy Otsu's method: finds the threshold that maximises
    between-class variance of a histogram, i.e. the value that best
    splits a bimodal distribution into two clusters. Standard approach
    for SAR water/land separation because the absolute backscatter level
    shifts scene-to-scene (wind, geometry, processing) — only the
    bimodal shape is stable.
    No extra dependency (skimage) needed for an algorithm this small."""
    finite = values[np.isfinite(values)]
    if len(finite) < n_bins:
        raise ValueError("Not enough valid pixels to compute a histogram-based threshold")

    hist, bin_edges = np.histogram(finite, bins=n_bins)
    bin_centers = (bin_edges[:-1] + bin_edges[1:]) / 2
    weight_total = hist.sum()

    weight_below = np.cumsum(hist)
    weight_above = weight_total - weight_below

    with np.errstate(invalid="ignore", divide="ignore"):
        mean_below = np.cumsum(hist * bin_centers) / weight_below
        mean_above = (
            np.sum(hist * bin_centers) - np.cumsum(hist * bin_centers)
        ) / weight_above

    with np.errstate(invalid="ignore", divide="ignore"):
        between_class_variance = (
            weight_below * weight_above * (mean_below - mean_above) ** 2
        )
    between_class_variance = np.nan_to_num(between_class_variance, nan=0.0)

    best_idx = int(np.argmax(between_class_variance))
    return float(bin_centers[best_idx])


# ---------------------------------------------------------------------------
# Scene discovery
# ---------------------------------------------------------------------------

def _seconds_from_target(item, target: datetime) -> float:
    item_dt = datetime.fromisoformat(
        item.properties["datetime"].replace("Z", "+00:00")
    )
    return abs((item_dt.replace(tzinfo=None) - target).total_seconds())


def _search_scene_element84(
    date: datetime,
    bbox: tuple[float, float, float, float],
    window_days: int = 12,
):
    """Search Element84 Earth Search for the nearest sentinel-1-grd scene.

    window_days defaults to 12 (one full Sentinel-1A repeat cycle) rather
    than 8, because with only 1A operational (2022-late-2024) a +/-8-day
    window can miss a pass at the extremes of the AOI.

    Returns a pystac.Item tagged with ._source = 'element84', or None."""
    import pystac_client
    from datetime import timedelta

    start = date - timedelta(days=window_days)
    end = date + timedelta(days=window_days)

    try:
        catalog = pystac_client.Client.open(STAC_ELEMENT84_URL)
    except Exception as exc:
        log.warning("Could not connect to Element84 Earth Search: %s", exc)
        return None

    try:
        search = catalog.search(
            collections=["sentinel-1-grd"],
            bbox=bbox,
            datetime=f"{start.strftime('%Y-%m-%d')}/{end.strftime('%Y-%m-%d')}",
        )
        items = list(search.items())
    except Exception as exc:
        log.warning("Element84 search failed: %s", exc)
        return None

    if not items:
        log.warning(
            "No sentinel-1-grd scenes found in Element84 within +/-%d days of %s.",
            window_days, date.date(),
        )
        return None

    items.sort(key=lambda it: _seconds_from_target(it, date))
    closest = items[0]
    closest._source = "element84"  # tag for downstream dispatch
    log.info(
        "Element84: found %d scene(s) within +/-%d days of %s — "
        "using closest: %s  (assets: %s)",
        len(items), window_days, date.date(),
        closest.properties["datetime"],
        ", ".join(closest.assets.keys()),
    )
    return closest


def _search_scene_asf(
    date: datetime,
    bbox: tuple[float, float, float, float],
    window_days: int = 12,
):
    """Search ASF for the nearest Sentinel-1 GRD_HD scene.

    Requires: pip install asf-search
    No credentials needed for metadata search; downloads require
    NASA Earthdata login (set in .env as NASA_EARTHDATA_* vars).

    Returns an asf_search result tagged with ._source = 'asf', or None."""
    try:
        import asf_search as asf
    except ImportError:
        log.warning("asf-search not installed — run: pip install asf-search")
        return None

    from datetime import timedelta

    lon_min, lat_min, lon_max, lat_max = bbox
    wkt = (
        f"POLYGON(({lon_min} {lat_min},{lon_max} {lat_min},"
        f"{lon_max} {lat_max},{lon_min} {lat_max},{lon_min} {lat_min}))"
    )
    start = (date - timedelta(days=window_days)).strftime("%Y-%m-%dT00:00:00Z")
    end = (date + timedelta(days=window_days)).strftime("%Y-%m-%dT23:59:59Z")

    try:
        results = asf.search(
            platform=[asf.PLATFORM.SENTINEL1],
            processingLevel=[asf.PRODUCT_TYPE.GRD_HD],
            intersectsWith=wkt,
            start=start,
            end=end,
            maxResults=20,
        )
    except Exception as exc:
        log.warning("ASF search failed: %s", exc)
        return None

    if not results:
        log.warning(
            "No Sentinel-1 GRD_HD scenes found in ASF within +/-%d days of %s.",
            window_days, date.date(),
        )
        return None

    def _asf_dt(r):
        s = r.properties.get("startTime", "")
        return datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)

    results = sorted(results, key=lambda r: abs((_asf_dt(r) - date).total_seconds()))
    best = results[0]
    best._source = "asf"
    log.info(
        "ASF: found %d scene(s) within +/-%d days of %s — "
        "using closest: %s",
        len(results), window_days, date.date(), best.properties.get("startTime"),
    )
    return best


def _search_scene(
    date: datetime,
    bbox: tuple[float, float, float, float],
    window_days: int = 12,
):
    """Find the nearest Sentinel-1 scene covering bbox around date.

    Tries sources in priority order:
      1. Element84 Earth Search (public, no auth, GRD DN data)
      2. ASF + HyP3 (NASA Earthdata credentials, produces RTC)

    Returns a scene result with a ._source attribute, or None."""
    result = _search_scene_element84(date, bbox, window_days)
    if result is not None:
        return result

    log.info("Element84 did not return a scene — trying ASF...")
    result = _search_scene_asf(date, bbox, window_days)
    if result is not None:
        return result

    log.error(
        "No Sentinel-1 scene found for %s in any available source. "
        "Check network connectivity and that the AOI/date are correct.",
        date.date(),
    )
    return None


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------

def _download_asset(href: str, cache_dir, local_filename: str) -> Path:
    """Download a remote HTTPS URL to a local cache file (full download,
    not streamed). Skips if already cached. Returns the local path.
    Does NOT handle s3:// URIs — callers must convert those first."""
    import requests

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)
    out_path = cache_dir / local_filename

    if out_path.exists() and out_path.stat().st_size > 0:
        log.info("Already downloaded %s, using cached copy", local_filename)
        return out_path

    log.info("Downloading %s — this may take a moment", local_filename)
    with requests.get(href, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        tmp_path = out_path.with_suffix(out_path.suffix + ".partial")
        with open(tmp_path, "wb") as fh:
            for chunk in resp.iter_content(chunk_size=1 << 20):
                fh.write(chunk)
        tmp_path.rename(out_path)

    log.info("Saved %s (%.1f MB)", out_path, out_path.stat().st_size / 1e6)
    return out_path


def _download_vv_via_asf(item_or_id, cache_dir: Path) -> Path:
    """Download a Sentinel-1 GRD_HD SAFE zip from ASF and extract the
    VV measurement tiff.

    Used when Element84 STAC metadata points to a requester-pays S3 URI
    (sentinel-s1-l1c bucket) that can't be fetched anonymously.  ASF
    hosts the same raw GRD data at HTTPS with NASA Earthdata auth, which
    we already have in .env.

    item_or_id: a pystac.Item from Element84 (preferred) or a bare scene
        ID string.  When a full Item is provided, the function can fall
        back to a date+orbit ASF search if granule_search returns nothing,
        which bypasses the Element84↔ASF naming mismatch.

    Returns the path to the extracted VV tiff (cached; won't re-download
    if already present)."""
    try:
        import asf_search as asf
    except ImportError:
        raise RuntimeError(
            "asf-search not installed. Run: pip install asf-search\n"
            "Needed to download Sentinel-1 GRD data from ASF."
        )
    import zipfile

    # Accept either a pystac Item or a bare string
    if hasattr(item_or_id, "id"):
        item = item_or_id
        scene_id = item.id       # e.g. S1A_IW_GRDH_1SDV_..._038573_048D39
        item_props = item.properties or {}
    else:
        item = None
        scene_id = str(item_or_id)
        item_props = {}

    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    vv_path = cache_dir / f"{scene_id}_vv.tif"
    if vv_path.exists() and vv_path.stat().st_size > 0:
        log.info("ASF VV already cached: %s", vv_path.name)
        return vv_path

    username = os.environ.get("NASA_EARTHDATA_USERNAME", "")
    password = os.environ.get("NASA_EARTHDATA_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "NASA_EARTHDATA_USERNAME / NASA_EARTHDATA_PASSWORD not set in "
            ".env — needed to download GRD data from ASF."
        )

    # ------------------------------------------------------------------
    # Strategy 1: search by granule name (exact, then without trailing hash)
    # ------------------------------------------------------------------
    log.info("Searching ASF for granule %s ...", scene_id)
    results = asf.granule_search([scene_id])
    if not results:
        scene_id_no_hash = "_".join(scene_id.split("_")[:-1])
        log.info("Name search empty — retrying without trailing hash: %s", scene_id_no_hash)
        results = asf.granule_search([scene_id_no_hash])

    # ------------------------------------------------------------------
    # Strategy 2: date + absolute-orbit search
    #   Element84 item IDs don't always match ASF's granule name field
    #   in NASA CMR, but the orbit number + date uniquely identifies the
    #   scene.  Orbit is the 7th underscore-separated component of the
    #   standard S1 scene ID; date comes from item.properties["datetime"].
    # ------------------------------------------------------------------
    if not results:
        log.info(
            "Granule name search returned nothing for %s — "
            "falling back to date+orbit search in ASF ...",
            scene_id,
        )
        try:
            parts = scene_id.split("_")
            # Standard S1 ID: S1A_IW_GRDH_1SDV_YYYYMMDDTHHMMSS_YYYYMMDDTHHMMSS_OOOOOO_MMMMMM
            # Orbit is parts[6]
            orbit = int(parts[6]) if len(parts) > 7 else None

            # Acquisition date from item properties (ISO-8601) or from ID
            dt_raw = item_props.get("datetime") or item_props.get("end_datetime") or ""
            if dt_raw:
                date_only = dt_raw[:10]          # "2021-06-30"
            else:
                # Fall back: extract from scene_id start-time component
                ts = parts[4]                    # "20210630T180159"
                date_only = f"{ts[:4]}-{ts[4:6]}-{ts[6:8]}"

            # Use a tight time window around the known acquisition time so we
            # only pick up the geographic segment that matches the Element84
            # scene (different segments of the same orbit start at different
            # UTC times — a whole-day window returns unrelated segments).
            from datetime import datetime as _dt, timedelta as _td, timezone as _tz
            ts_str = parts[4]  # e.g. "20210630T180159"
            try:
                scene_start = _dt(
                    int(ts_str[0:4]), int(ts_str[4:6]), int(ts_str[6:8]),
                    int(ts_str[9:11]), int(ts_str[11:13]), int(ts_str[13:15]),
                    tzinfo=_tz.utc,
                )
                t_search_start = (scene_start - _td(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
                t_search_end   = (scene_start + _td(minutes=30)).strftime("%Y-%m-%dT%H:%M:%SZ")
            except (ValueError, IndexError):
                scene_start = None
                t_search_start = f"{date_only}T00:00:00Z"
                t_search_end   = f"{date_only}T23:59:59Z"

            # Add AOI filter from the item's own bounding box so only
            # Lagos-covering slices are returned.
            intersects_wkt = None
            if item is not None:
                item_bbox = getattr(item, "bbox", None)
                if item_bbox:
                    w, s, e, n = item_bbox
                    intersects_wkt = f"POLYGON(({w} {s},{e} {s},{e} {n},{w} {n},{w} {s}))"

            search_kw: dict = dict(
                platform=[asf.PLATFORM.SENTINEL1],
                processingLevel=[asf.PRODUCT_TYPE.GRD_HD],
                start=t_search_start,
                end=t_search_end,
                maxResults=10,
            )
            if orbit:
                search_kw["absoluteOrbit"] = orbit
            if intersects_wkt:
                search_kw["intersectsWith"] = intersects_wkt
            log.info(
                "  time window %s – %s, orbit=%s, AOI=%s",
                t_search_start, t_search_end, orbit or "any",
                intersects_wkt[:50] if intersects_wkt else "none",
            )

            results = asf.search(**search_kw)
            if results:
                # Sort by temporal proximity to the Element84 scene start time
                if scene_start is not None:
                    def _asf_dt(r):
                        name = r.properties.get("sceneName", "")
                        p = name.split("_")
                        if len(p) > 4:
                            t = p[4]
                            try:
                                return _dt(
                                    int(t[0:4]), int(t[4:6]), int(t[6:8]),
                                    int(t[9:11]), int(t[11:13]), int(t[13:15]),
                                    tzinfo=_tz.utc,
                                )
                            except (ValueError, IndexError):
                                pass
                        return scene_start
                    results = sorted(
                        results,
                        key=lambda r: abs((_asf_dt(r) - scene_start).total_seconds()),
                    )
                log.info(
                    "Date+orbit+AOI search found %d result(s), best: %s",
                    len(results),
                    results[0].properties.get("sceneName", "?"),
                )
        except Exception as exc:
            log.warning("Date+orbit fallback search failed: %s", exc)

    if not results:
        raise RuntimeError(
            f"ASF search returned nothing for '{scene_id}' via name search "
            f"or date+orbit fallback.  Check network / Earthdata credentials."
        )

    # Use only the first (best) result
    best = results[0]
    session = asf.ASFSession().auth_with_creds(username, password)

    # Determine the filename ASF will write so we can locate it after download
    asf_filename = best.properties.get("fileName") or f"{scene_id}.zip"
    if not asf_filename.endswith(".zip"):
        asf_filename += ".zip"
    zip_path = cache_dir / asf_filename

    if not (zip_path.exists() and zip_path.stat().st_size > 0):
        log.info(
            "Downloading %s from ASF (GRD_HD zip, ~700 MB–1.5 GB — "
            "this will take several minutes on a typical connection)...",
            asf_filename,
        )
        # Download only the single best result
        asf.ASFSearchResults([best]).download(path=cache_dir, session=session, processes=1)
        if not (zip_path.exists() and zip_path.stat().st_size > 0):
            # fileName property may have been wrong; scan for any new zip
            new_zips = list(cache_dir.glob("S1*.zip"))
            if new_zips:
                newest = max(new_zips, key=lambda p: p.stat().st_mtime)
                log.info("Renaming %s → %s", newest.name, zip_path.name)
                newest.rename(zip_path)
            else:
                raise RuntimeError(
                    f"Expected a .zip in {cache_dir} after ASF download but found none."
                )
    else:
        log.info("ASF zip already downloaded: %s", zip_path.name)

    log.info("Extracting VV measurement tiff from %s ...", zip_path.name)
    with zipfile.ZipFile(zip_path) as zf:
        vv_entries = [
            n for n in zf.namelist()
            if "measurement" in n and "vv" in n.lower() and n.lower().endswith(".tiff")
        ]
        if not vv_entries:
            raise RuntimeError(
                f"No VV measurement tiff found inside {zip_path.name}. "
                f"Entries: {[n for n in zf.namelist() if 'measurement' in n]}"
            )
        log.info("Extracting %s ...", vv_entries[0])
        with zf.open(vv_entries[0]) as src, open(vv_path, "wb") as dst:
            dst.write(src.read())

    zip_path.unlink()  # remove zip, keep extracted tif
    log.info("Extracted %s (%.1f MB)", vv_path.name, vv_path.stat().st_size / 1e6)
    return vv_path


def _hyp3_rtc(scene_name: str) -> Path:
    """Submit a HyP3 RTC job for one Sentinel-1 GRD scene and return
    the path to the downloaded VV tif.

    Uses NASA_EARTHDATA_USERNAME / NASA_EARTHDATA_PASSWORD from the
    environment (loaded from .env by floodsight.config).
    Requires: pip install hyp3-sdk

    Processing takes ~30-60 min; output is cached so each scene is only
    submitted once. The HyP3 output format (linear sigma0 float32 GeoTiff)
    is identical to what Planetary Computer provided for sentinel-1-rtc."""
    try:
        from hyp3_sdk import HyP3
    except ImportError:
        raise RuntimeError(
            "hyp3-sdk not installed. Run: pip install hyp3-sdk\n"
            "Then retry — HyP3 RTC processing takes ~30-60 min per scene "
            "but results are cached locally."
        )
    import zipfile

    cache_dir = SAR_OUT_DIR / "cache"
    cache_dir.mkdir(parents=True, exist_ok=True)
    vv_path = cache_dir / f"{scene_name}_VV.tif"
    if vv_path.exists() and vv_path.stat().st_size > 0:
        log.info("HyP3 RTC already cached: %s", vv_path)
        return vv_path

    username = os.environ.get("NASA_EARTHDATA_USERNAME", "")
    password = os.environ.get("NASA_EARTHDATA_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "NASA_EARTHDATA_USERNAME / NASA_EARTHDATA_PASSWORD not set in "
            ".env — needed for HyP3 RTC fallback."
        )

    # The HyP3 output zip is named differently from the input scene, e.g.:
    #   input:  S1A_IW_GRDH_1SDV_20210630T180159_..._9F1C
    #   output: S1A_IW_20210630T180159_DVP_RTC30_G_gpuned_27AC.zip
    # Both contain the scene's start timestamp, so we use that for caching.
    scene_ts = scene_name.split("_")[4] if len(scene_name.split("_")) > 4 else ""
    existing_zip = (
        next(cache_dir.glob(f"*{scene_ts}*.zip"), None)
        if scene_ts else None
    )

    if existing_zip:
        log.info("Found existing HyP3 zip %s — extracting without re-submitting.", existing_zip.name)
        zip_path = existing_zip
    else:
        hyp3 = HyP3(username=username, password=password)
        log.info("Submitting HyP3 RTC job for %s (takes ~30-60 min)...", scene_name)
        jobs = hyp3.submit_rtc_job(
            granule=scene_name,
            dem_matching=False,
            include_dem=False,
            include_inc_map=False,
            include_rgb=False,
            include_scattering_area=False,
            resolution=30,
        )
        log.info("Waiting for HyP3 processing to complete...")
        jobs = hyp3.watch(jobs)
        job = jobs[0]
        if job.status_code != "SUCCEEDED":
            raise RuntimeError(f"HyP3 job {job.job_id} failed with status: {job.status_code}")

        # Track which zips exist before download; pick the new one afterward.
        # (HyP3 output naming differs from the input scene name.)
        before_zips = set(cache_dir.rglob("*.zip"))
        log.info("HyP3 job succeeded — downloading output...")
        job.download_files(cache_dir)
        new_zips = sorted(
            (z for z in cache_dir.rglob("*.zip") if z not in before_zips),
            key=lambda p: p.stat().st_mtime, reverse=True,
        )
        if not new_zips:
            raise RuntimeError(
                f"Expected a .zip in {cache_dir} after HyP3 download but found none. "
                f"Check that the HyP3 job actually produced output."
            )
        zip_path = new_zips[0]
        log.info("HyP3 downloaded: %s", zip_path.name)

    with zipfile.ZipFile(zip_path) as zf:
        vv_entry = next(
            (n for n in zf.namelist() if n.endswith("_VV.tif")), None
        )
        if vv_entry is None:
            raise RuntimeError(
                f"No *_VV.tif found inside {zip_path.name}: {zf.namelist()}"
            )
        log.info("Extracting %s → %s ...", vv_entry, vv_path.name)
        with zf.open(vv_entry) as src, open(vv_path, "wb") as dst:
            dst.write(src.read())
    zip_path.unlink()  # remove zip, keep the tif
    log.info("Extracted %s (%.1f MB)", vv_path.name, vv_path.stat().st_size / 1e6)
    return vv_path


# ---------------------------------------------------------------------------
# Water mask computation
# ---------------------------------------------------------------------------

def _build_water_mask(local_path: Path, bbox, is_rtc: bool = False):
    """Read a locally-cached SAR VV tif, clip to bbox+buffer, compute
    Otsu water threshold, and return a uint8 0/1 water mask DataArray.

    is_rtc=True  → data is calibrated sigma0 linear (from HyP3/PC RTC);
                   convert with 10*log10. Sanity range: -30 to +5 dB.
    is_rtc=False → data is raw GRD DN amplitude (from Element84);
                   convert with 10*log10(DN). Sanity range: 15 to 50 dB.
    Either way the Otsu logic is identical; only the fallback threshold
    and the sanity window differ."""
    import rioxarray

    da = rioxarray.open_rasterio(local_path).squeeze().load()

    buffer_deg = 0.05
    lon_min, lat_min, lon_max, lat_max = bbox
    da = da.rio.clip_box(
        lon_min - buffer_deg, lat_min - buffer_deg,
        lon_max + buffer_deg, lat_max + buffer_deg,
        crs="EPSG:4326",
    )

    # Convert to log scale. 10*log10 works for both power (RTC) and
    # amplitude-squared-equivalent (DN): the relative land/water contrast
    # is preserved and Otsu only needs the bimodal shape.
    vv_log = 10 * np.log10(da.where(da > 0))
    vv_values = vv_log.to_numpy()

    if is_rtc:
        fallback = WATER_VV_THRESHOLD_DB       # sigma0 dB
        sanity_lo, sanity_hi = -30.0, 5.0
    else:
        fallback = WATER_VV_THRESHOLD_DN_DB    # 10*log10(DN)
        sanity_lo, sanity_hi = 15.0, 50.0

    try:
        threshold = _otsu_threshold(vv_values)
        if not (sanity_lo < threshold < sanity_hi):
            log.warning(
                "Otsu threshold (%.2f) outside sanity range (%.0f, %.0f) — "
                "using fallback %.2f.",
                threshold, sanity_lo, sanity_hi, fallback,
            )
            threshold = fallback
        else:
            log.info("Otsu water threshold: %.2f (sanity range %.0f–%.0f)",
                     threshold, sanity_lo, sanity_hi)
    except ValueError:
        log.warning(
            "Could not compute Otsu threshold (too few valid pixels) — "
            "using fallback %.2f.", fallback,
        )
        threshold = fallback

    water_mask = (vv_log < threshold).astype("uint8")
    water_mask = water_mask.rio.write_nodata(None)
    return water_mask


def _water_mask_from_element84_item(item, bbox):
    """Download the VV asset from an Element84 sentinel-1-grd item and
    return a water mask.

    Element84's sentinel-1-grd VV assets live in the requester-pays S3
    bucket s3://sentinel-s1-l1c, which can't be fetched with a plain
    requests.get() call.  When we detect an s3:// href we fall back to
    downloading the same raw GRD scene from ASF via HTTPS (NASA Earthdata
    credentials from .env).  The extracted VV tiff is identical data."""
    # Try common VV asset keys (Element84 GRD uses lowercase 'vv')
    vv_asset = None
    for key in ("vv", "VV", "IW_VV"):
        if key in item.assets:
            vv_asset = item.assets[key]
            break

    if vv_asset is None:
        log.error(
            "No VV asset found in Element84 item %s. "
            "Available assets: %s",
            item.id, list(item.assets.keys()),
        )
        return None

    href = vv_asset.href

    if href.startswith("s3://"):
        # Requester-pays S3 — can't download anonymously.
        # Strategy A: find the equivalent GRD in ASF and download the SAFE zip.
        # Strategy B (fallback): if ASF doesn't have this geographic slice, run
        #   HyP3 RTC on the nearest ASF-available scene covering the same AOI.
        log.info(
            "VV asset is a requester-pays S3 URI (%s) — "
            "trying ASF direct download first.",
            href,
        )
        try:
            local_path = _download_vv_via_asf(item, SAR_OUT_DIR / "cache")
            return _build_water_mask(local_path, bbox, is_rtc=False)
        except Exception as exc:
            log.warning(
                "ASF direct download failed for %s: %s\n"
                "  → Falling back to HyP3 RTC for a Lagos-intersecting "
                "ASF scene from the same date (takes ~30-60 min).",
                item.id, exc,
            )

        # HyP3 fallback: search ASF for any IW GRD_HD scene covering the
        # Lagos AOI within ±8 days of this item's acquisition date.
        try:
            from datetime import datetime as _dtt
            dt_str = (item.properties or {}).get("datetime", "")[:10]  # "2021-06-30"
            fallback_date = _dtt.fromisoformat(dt_str)
            asf_item = _search_scene_asf(fallback_date, bbox, window_days=8)
        except Exception as exc2:
            log.error("HyP3 fallback: ASF scene search failed: %s", exc2)
            return None

        if asf_item is None:
            log.error(
                "HyP3 fallback: no ASF scene found for Lagos AOI within "
                "±8 days of %s. Aborting.", dt_str,
            )
            return None

        log.info(
            "HyP3 fallback: submitting RTC job for %s (30-60 min) ...",
            asf_item.properties.get("sceneName", "?"),
        )
        return _water_mask_from_asf_item(asf_item, bbox)

    else:
        local_path = _download_asset(href, SAR_OUT_DIR / "cache", f"{item.id}_vv.tif")
        return _build_water_mask(local_path, bbox, is_rtc=False)


def _water_mask_from_asf_item(asf_result, bbox):
    """Process an ASF scene via HyP3 RTC and return a water mask."""
    scene_name = asf_result.properties.get("sceneName") or asf_result.properties.get("fileID")
    local_path = _hyp3_rtc(scene_name)
    return _build_water_mask(local_path, bbox, is_rtc=True)


def _water_mask_from_item(item, bbox=AOI_BBOX):
    """Dispatch to the right water-mask builder based on item source."""
    source = getattr(item, "_source", "element84")
    if source == "asf":
        return _water_mask_from_asf_item(item, bbox)
    else:
        return _water_mask_from_element84_item(item, bbox)


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def detect_flood_extent(
    pre_event_date: datetime,
    during_event_date: datetime,
    bbox: tuple[float, float, float, float] = AOI_BBOX,
    window_days: int = 12,
):
    """Returns path to a boolean flood-extent raster (during-event water
    minus pre-existing permanent water), or None on failure."""
    pre_item = _search_scene(pre_event_date, bbox, window_days=window_days)
    during_item = _search_scene(during_event_date, bbox, window_days=window_days)

    if pre_item is None or during_item is None:
        log.error(
            "Could not find both pre- and during-event scenes within "
            "+/-%d days; aborting. Try --window-days with a larger value.",
            window_days,
        )
        return None

    pre_water = _water_mask_from_item(pre_item, bbox)
    during_water = _water_mask_from_item(during_item, bbox)

    if pre_water is None or during_water is None:
        log.error("Failed to build water mask for one or both scenes.")
        return None

    # Align grids in case scenes have slightly different footprints/orbits
    during_water = during_water.rio.reproject_match(pre_water)

    # Use explicit == comparisons on uint8 (not bitwise &/~): bitwise NOT
    # on uint8 0 gives 255, not 1. See _build_water_mask docstring.
    flood_extent = (during_water == 1) & (pre_water == 0)

    SAR_OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = SAR_OUT_DIR / f"flood_extent_{during_event_date.strftime('%Y%m%d')}.tif"
    flood_extent.astype("uint8").rio.to_raster(out_path)
    log.info("Saved flood extent mask to %s", out_path)
    return out_path


if __name__ == "__main__":
    import argparse

    # Load .env so NASA_EARTHDATA_* are available for the HyP3 fallback
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass

    parser = argparse.ArgumentParser()
    parser.add_argument("--pre", required=True, help="Pre-event date YYYY-MM-DD")
    parser.add_argument("--during", required=True, help="During/post-event date YYYY-MM-DD")
    parser.add_argument(
        "--window-days", type=int, default=12,
        help="Search +/- this many days around each target date (default: 12)",
    )
    args = parser.parse_args()
    detect_flood_extent(
        datetime.strptime(args.pre, "%Y-%m-%d"),
        datetime.strptime(args.during, "%Y-%m-%d"),
        window_days=args.window_days,
    )
