"""
Download CHIRPS daily rainfall rasters (Africa subset) for a date range.

Source: Climate Hazards Center, UC Santa Barbara — public domain, no
account needed.
  https://www.chc.ucsb.edu/data/chirps
  Direct HTTPS index (Africa daily, 0.05deg, GeoTIFF):
    https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_daily/tifs/p05/{year}/
    chirps-v2.0.{year}.{mm}.{dd}.tif.gz

CHIRPS v3 (operational since Jan 2025, recommended for new work; v2
production ends Dec 2026) lives at:
  https://data.chc.ucsb.edu/products/CHIRPS/v3.0/
See https://chc.ucsb.edu/data/chirps3 for the current path layout, which
CHC may still be finalizing per-region directories for — check there if
the v3 URL pattern below has moved.

Usage:
    python -m floodsight.download.rainfall_chirps --start 2024-09-01 --end 2024-09-10
"""

from __future__ import annotations

import argparse
import gzip
import logging
import shutil
from datetime import datetime, timedelta
from pathlib import Path

import requests

from floodsight.config import RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

RAINFALL_OUT_DIR = RAW_DIR / "rainfall" / "chirps"
CHIRPS_BASE = "https://data.chc.ucsb.edu/products/CHIRPS-2.0/africa_daily/tifs/p05"


def download_day(date: datetime, out_dir: Path = RAINFALL_OUT_DIR) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    fname = f"chirps-v2.0.{date.year}.{date.month:02d}.{date.day:02d}.tif"
    out_path = out_dir / fname
    if out_path.exists():
        log.info("Already have %s, skipping", fname)
        return out_path

    gz_url = f"{CHIRPS_BASE}/{date.year}/{fname}.gz"
    log.info("Downloading %s", gz_url)
    resp = requests.get(gz_url, stream=True, timeout=60)
    if resp.status_code == 404:
        log.warning("No CHIRPS file for %s (not yet published or out of range)", date.date())
        return None
    resp.raise_for_status()

    gz_path = out_path.with_suffix(".tif.gz")
    with open(gz_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    with gzip.open(gz_path, "rb") as f_in, open(out_path, "wb") as f_out:
        shutil.copyfileobj(f_in, f_out)
    gz_path.unlink()
    log.info("Saved %s", out_path)
    return out_path


def download_range(start: datetime, end: datetime) -> list[Path]:
    paths = []
    d = start
    while d <= end:
        p = download_day(d)
        if p:
            paths.append(p)
        d += timedelta(days=1)
    return paths


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    download_range(
        datetime.strptime(args.start, "%Y-%m-%d"),
        datetime.strptime(args.end, "%Y-%m-%d"),
    )
