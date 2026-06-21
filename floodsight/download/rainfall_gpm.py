"""
Download GPM IMERG rainfall (the near-real-time upgrade path from CHIRPS,
per the README's "Next development phase" item).

Source: NASA GES DISC, via NASA Earthdata. Requires a free Earthdata
account: https://urs.earthdata.nasa.gov/users/new
  Dataset landing page (Final Run, daily, 0.1deg):
    https://www.earthdata.nasa.gov/data/catalog/ges-disc-gpm-3imergdf-07
  Near-real-time Early/Late Run variants (4hr / 14hr latency) are what
  you'd use in production; Final Run (3.5-month latency) is for
  validation/backtesting only.

This module uses NASA's official `earthaccess` Python library, which
handles Earthdata Login auth and the GES DISC OPeNDAP/granule search for
you — much less brittle than hand-building download URLs.
    pip install earthaccess

Auth: set NASA_EARTHDATA_USERNAME / NASA_EARTHDATA_PASSWORD in your .env
(see floodsight/config.py Credentials), or run `earthaccess.login()`
interactively once and it will cache a token in ~/.netrc.

Usage:
    python -m floodsight.download.rainfall_gpm --start 2024-09-01 --end 2024-09-10
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime

from floodsight.config import AOI_BBOX, CREDENTIALS, RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

RAINFALL_OUT_DIR = RAW_DIR / "rainfall" / "gpm_imerg"
GPM_SHORT_NAME = "GPM_3IMERGDF"  # Final Run, daily, 0.1deg, V07


def download_gpm_range(start: datetime, end: datetime) -> list[str]:
    import earthaccess

    RAINFALL_OUT_DIR.mkdir(parents=True, exist_ok=True)

    if CREDENTIALS.nasa_earthdata_username and CREDENTIALS.nasa_earthdata_password:
        auth = earthaccess.login(strategy="environment")
    else:
        log.info(
            "No NASA_EARTHDATA_USERNAME/PASSWORD in .env — falling back to "
            "interactive/.netrc login. Run earthaccess.login() once by hand "
            "if this fails."
        )
        auth = earthaccess.login()

    if not auth.authenticated:
        log.error(
            "NASA Earthdata authentication failed. Create a free account at "
            "https://urs.earthdata.nasa.gov/users/new and set credentials "
            "in .env (see .env.example)."
        )
        return []

    results = earthaccess.search_data(
        short_name=GPM_SHORT_NAME,
        bounding_box=AOI_BBOX,
        temporal=(start.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d")),
    )
    log.info("Found %d GPM IMERG granules", len(results))
    files = earthaccess.download(results, str(RAINFALL_OUT_DIR))
    return files


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", required=True, help="YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="YYYY-MM-DD")
    args = parser.parse_args()
    download_gpm_range(
        datetime.strptime(args.start, "%Y-%m-%d"),
        datetime.strptime(args.end, "%Y-%m-%d"),
    )
