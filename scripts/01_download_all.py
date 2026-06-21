"""
Run all data downloads for the AOI. Each download is independent and
resumable (skips files already on disk) — safe to re-run or to comment
out sources you don't need yet.

Usage:
    python scripts/01_download_all.py
    python scripts/01_download_all.py --skip-osm --skip-gpm
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def main(args):
    from floodsight.download import boundaries, dem, landcover, population, rainfall_chirps

    log.info("=== Admin boundaries ===")
    boundaries.download_all_boundaries()

    log.info("=== DEM (Copernicus GLO-30) ===")
    dem.download_dem_for_aoi()

    log.info("=== Land cover (ESA WorldCover) ===")
    landcover.download_landcover_for_aoi()

    log.info("=== Population (WorldPop) ===")
    population.download_population()

    if not args.skip_osm:
        log.info("=== OSM (Geofabrik) — this is a large download ===")
        from floodsight.download import osm

        pbf = osm.download_osm_pbf()
        osm.extract_layers_for_aoi(pbf)
    else:
        log.info("Skipping OSM download (--skip-osm)")

    if not args.skip_rainfall:
        log.info("=== CHIRPS rainfall (last 30 days as a starter sample) ===")
        from datetime import datetime, timedelta

        end = datetime.utcnow() - timedelta(days=3)  # CHIRPS has a few days' latency
        start = end - timedelta(days=30)
        rainfall_chirps.download_range(start, end)
    else:
        log.info("Skipping CHIRPS download (--skip-rainfall)")

    if not args.skip_gpm:
        log.info("=== GPM IMERG (requires NASA Earthdata credentials in .env) ===")
        try:
            from floodsight.download import rainfall_gpm
            from datetime import datetime, timedelta

            end = datetime.utcnow() - timedelta(days=1)
            start = end - timedelta(days=7)
            rainfall_gpm.download_gpm_range(start, end)
        except Exception as exc:  # noqa: BLE001
            log.warning("GPM IMERG download skipped/failed: %s", exc)
    else:
        log.info("Skipping GPM download (--skip-gpm)")

    log.info("Done. Check data/raw/ for downloaded files.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-osm", action="store_true")
    parser.add_argument("--skip-rainfall", action="store_true")
    parser.add_argument("--skip-gpm", action="store_true")
    main(parser.parse_args())
