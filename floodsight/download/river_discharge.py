"""
Download river discharge data from GloFAS (Global Flood Awareness System) —
the discharge input needed for the HAND-based depth model
(floodsight/processing/depth_hand.py, ROADMAP.md Phase 1).

Source: Copernicus Early Warning Data Store (GloFAS was moved here from
the general Climate Data Store in 2024 — use this URL, not the old
cds.climate.copernicus.eu one referenced in older tutorials):
  https://ewds.climate.copernicus.eu/datasets/cems-glofas-historical
  https://ewds.climate.copernicus.eu/datasets/cems-glofas-forecast

Auth: free account at https://ewds.climate.copernicus.eu/ , then put your
Personal Access Token (from https://ewds.climate.copernicus.eu/profile)
into ~/.cdsapirc:

    url: https://ewds.climate.copernicus.eu/api
    key: <PERSONAL-ACCESS-TOKEN>

    pip install cdsapi

Usage:
    python -m floodsight.download.river_discharge --years 2022 2024 2025
"""

from __future__ import annotations

import argparse
import logging

from floodsight.config import AOI_BBOX, RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

DISCHARGE_OUT_DIR = RAW_DIR / "river_discharge"


def download_historical_discharge(years: list[int]) -> str:
    """Downloads GloFAS historical (reanalysis) discharge for the given
    years, clipped to the AOI bounding box. Returns the output file path."""
    import cdsapi

    DISCHARGE_OUT_DIR.mkdir(parents=True, exist_ok=True)
    lon_min, lat_min, lon_max, lat_max = AOI_BBOX
    # CDS area format is [North, West, South, East]
    area = [lat_max, lon_min, lat_min, lon_max]

    out_path = DISCHARGE_OUT_DIR / f"glofas_historical_{min(years)}_{max(years)}.grib"

    client = cdsapi.Client()
    request = {
        "system_version": ["version_4_0"],
        "hydrological_model": ["lisflood"],
        "product_type": ["consolidated"],
        "variable": ["river_discharge_in_the_last_24_hours"],
        "hyear": [str(y) for y in years],
        "hmonth": [f"{m:02d}" for m in range(1, 13)],
        "hday": [f"{d:02d}" for d in range(1, 32)],
        "data_format": "grib2",
        "download_format": "unarchived",
        "area": area,
    }
    log.info("Requesting GloFAS historical discharge for years %s, area %s", years, area)
    client.retrieve("cems-glofas-historical", request).download(str(out_path))
    log.info("Saved %s", out_path)
    return str(out_path)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", nargs="+", type=int, required=True)
    args = parser.parse_args()
    download_historical_discharge(args.years)
