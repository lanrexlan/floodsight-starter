"""
Download WorldPop population data for Nigeria.

Primary source (direct .tif, no account needed):
  WorldPop's own data host (the storage backing data.worldpop.org /
  hub.worldpop.org — confirmed live June 2026):
  https://worldpop-public-data.soton.ac.uk/GIS/Population/Global_2000_2020_Constrained/2020/maxar_v1/NGA/

  Mirror (same file, browsable via HDX's UI if the direct link below
  ever moves):
  https://data.humdata.org/dataset/worldpop-population-counts-for-nigeria

Canonical source / full catalogue of products and years:
  https://hub.worldpop.org/geodata/summary?id=28031  (100m unconstrained)
  https://hub.worldpop.org/project/list              (browse all products)
  Bottom-up bespoke Nigeria estimates (WOPR):
  https://wopr.worldpop.org/download/554

Usage:
    python -m floodsight.download.population
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from floodsight.config import RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

POPULATION_OUT_DIR = RAW_DIR / "population"

# Confirmed live June 2026 (see docstring above). The "maxar_v1" folder
# name is not obvious from the WorldPop website's own navigation — it's
# the actual storage path for the constrained, UN-adjusted 100m 2020
# country product, verified by fetching the directory listing directly.
WORLDPOP_DIRECT_URL = (
    "https://worldpop-public-data.soton.ac.uk/GIS/Population/"
    "Global_2000_2020_Constrained/2020/maxar_v1/NGA/"
    "nga_ppp_2020_UNadj_constrained.tif"
)


def download_population(out_dir: Path = POPULATION_OUT_DIR) -> Path | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "nga_ppp_2020_UNadj_constrained.tif"
    if out_path.exists():
        log.info("Already have %s, skipping", out_path.name)
        return out_path

    log.info("Downloading %s", WORLDPOP_DIRECT_URL)
    try:
        resp = requests.get(WORLDPOP_DIRECT_URL, stream=True, timeout=120)
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.error(
            "Direct WorldPop download failed (%s). Browse "
            "https://data.humdata.org/dataset/worldpop-population-counts-for-nigeria "
            "and download the current 100m UN-adjusted constrained .tif by hand into %s",
            exc,
            out_dir,
        )
        return None

    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    log.info("Saved %s", out_path)
    return out_path


if __name__ == "__main__":
    download_population()
