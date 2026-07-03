"""
Download ESA WorldCover 10m land cover tiles covering the AOI.

Source: ESA WorldCover (VITO), AWS Open Data Registry.
  https://registry.opendata.aws/esa-worldcover-vito/
  Bucket: s3://esa-worldcover (region eu-central-1, public, no-sign-request)
  v200 (2021) layout:
    s3://esa-worldcover/v200/2021/map/ESA_WorldCover_10m_2021_v200_{tile}_Map.tif
  where {tile} is a 3x3-degree tile id like "N00E000".

Project homepage / alternative download channels (Zenodo bulk archives,
Terrascope viewer, Google Earth Engine asset ESA/WorldCover/v200):
  https://esa-worldcover.org/en/data-access

Usage:
    python -m floodsight.download.landcover
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import requests

from floodsight.config import AOI_BBOX, RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

S3_HTTPS_BASE = "https://esa-worldcover.s3.eu-central-1.amazonaws.com"
WORLDCOVER_VERSION = "v200"
WORLDCOVER_YEAR = "2021"
LANDCOVER_OUT_DIR = RAW_DIR / "landcover"


def _tile_id(lat_deg: int, lon_deg: int) -> str:
    """ESA WorldCover tiles are on a 3-degree grid, named by their SW corner."""
    lat_origin = lat_deg - (lat_deg % 3) if lat_deg >= 0 else lat_deg - (lat_deg % 3) - 3
    lon_origin = lon_deg - (lon_deg % 3) if lon_deg >= 0 else lon_deg - (lon_deg % 3) - 3
    ns = "N" if lat_origin >= 0 else "S"
    ew = "E" if lon_origin >= 0 else "W"
    return f"{ns}{abs(lat_origin):02d}{ew}{abs(lon_origin):03d}"


def tiles_for_bbox(bbox: tuple[float, float, float, float]) -> list[str]:
    lon_min, lat_min, lon_max, lat_max = bbox
    lat_start, lat_end = math.floor(lat_min), math.floor(lat_max)
    lon_start, lon_end = math.floor(lon_min), math.floor(lon_max)
    seen = set()
    for lat_deg in range(lat_start, lat_end + 1):
        for lon_deg in range(lon_start, lon_end + 1):
            seen.add(_tile_id(lat_deg, lon_deg))
    return sorted(seen)


def download_tile(tile_id: str, out_dir: Path = LANDCOVER_OUT_DIR) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"ESA_WorldCover_10m_{WORLDCOVER_YEAR}_{WORLDCOVER_VERSION}_{tile_id}_Map.tif"
    out_path = out_dir / fname
    if out_path.exists():
        log.info("Already have %s, skipping", fname)
        return out_path

    url = f"{S3_HTTPS_BASE}/{WORLDCOVER_VERSION}/{WORLDCOVER_YEAR}/map/{fname}"
    log.info("Downloading %s", url)
    resp = requests.get(url, stream=True, timeout=60)
    if resp.status_code == 404:
        log.warning("Tile not found (likely ocean-only tile): %s", tile_id)
        return None
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    log.info("Saved %s", out_path)
    return out_path


def download_landcover_for_aoi(bbox: tuple[float, float, float, float] = AOI_BBOX) -> list[Path]:
    paths = []
    for tile in tiles_for_bbox(bbox):
        p = download_tile(tile)
        if p:
            paths.append(p)
    return paths


if __name__ == "__main__":
    download_landcover_for_aoi()
