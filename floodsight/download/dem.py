"""
Download Copernicus DEM GLO-30 elevation tiles covering the AOI.

Source: Copernicus DEM (Sinergise), AWS Open Data Registry.
  https://registry.opendata.aws/copernicus-dem/
  Bucket: s3://copernicus-dem-30m  (public, no-sign-request)
  Tile naming: Copernicus_DSM_COG_10_N06_00_E003_00_DEM/...DEM.tif
  (10 = arcsec resolution code for GLO-30; N06/E003 = 1-degree tile origin)

Alternative source (if the AWS bucket is throttled or a tile is missing
from the public AWS release): OpenTopography, which re-hosts the same
GLO-30 DGED 2023_1 release —
  https://portal.opentopography.org/raster?opentopoID=OTSDEM.032021.4326.3
  (requires a free OpenTopography API key for their REST API; the AWS
  route below does not require any account.)

Usage:
    python -m floodsight.download.dem
"""

from __future__ import annotations

import logging
import math
from pathlib import Path

import requests

from floodsight.config import AOI_BBOX, RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

S3_HTTPS_BASE = "https://copernicus-dem-30m.s3.amazonaws.com"
DEM_OUT_DIR = RAW_DIR / "dem"


def _tile_name(lat_deg: int, lon_deg: int) -> str:
    """Build the Copernicus GLO-30 1-degree tile folder/file name."""
    ns = "N" if lat_deg >= 0 else "S"
    ew = "E" if lon_deg >= 0 else "W"
    lat_code = f"{ns}{abs(lat_deg):02d}_00"
    lon_code = f"{ew}{abs(lon_deg):03d}_00"
    folder = f"Copernicus_DSM_COG_10_{lat_code}_{lon_code}_DEM"
    return folder


def tiles_for_bbox(bbox: tuple[float, float, float, float]) -> list[str]:
    """Return the list of 1-degree GLO-30 tile names covering bbox."""
    lon_min, lat_min, lon_max, lat_max = bbox
    lat_start, lat_end = math.floor(lat_min), math.floor(lat_max)
    lon_start, lon_end = math.floor(lon_min), math.floor(lon_max)
    tiles = []
    for lat_deg in range(lat_start, lat_end + 1):
        for lon_deg in range(lon_start, lon_end + 1):
            tiles.append(_tile_name(lat_deg, lon_deg))
    return tiles


def download_tile(tile_name: str, out_dir: Path = DEM_OUT_DIR) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{tile_name}.tif"
    if out_path.exists():
        log.info("Already have %s, skipping", out_path.name)
        return out_path

    url = f"{S3_HTTPS_BASE}/{tile_name}/{tile_name}.tif"
    log.info("Downloading %s", url)
    resp = requests.get(url, stream=True, timeout=60)
    if resp.status_code == 404:
        log.warning("Tile not found at %s (ocean tile or not yet public): %s", url, tile_name)
        return None
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    log.info("Saved %s", out_path)
    return out_path


def download_dem_for_aoi(bbox: tuple[float, float, float, float] = AOI_BBOX) -> list[Path]:
    paths = []
    for tile in tiles_for_bbox(bbox):
        p = download_tile(tile)
        if p:
            paths.append(p)
    if not paths:
        log.error(
            "No DEM tiles downloaded. Check network access to "
            "copernicus-dem-30m.s3.amazonaws.com, or fall back to OpenTopography."
        )
    return paths


if __name__ == "__main__":
    download_dem_for_aoi()
