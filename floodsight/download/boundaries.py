"""
Download Nigeria administrative boundaries (for clipping the AOI precisely
to Eti-Osa, Lagos Island, and Kosofe LGAs).

Source: geoBoundaries — open license, standardized political admin
boundaries, mirrored on GitHub (versioned, stable raw URLs) and on HDX.
  https://www.geoboundaries.org/
  https://data.humdata.org/dataset/geoboundaries-admin-boundaries-for-nigeria

ADM2 in Nigeria corresponds to LGAs (Local Government Areas), which is
the level you want for Eti-Osa / Lagos Island / Kosofe.

Usage:
    python -m floodsight.download.boundaries
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from floodsight.config import RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

BOUNDARIES_OUT_DIR = RAW_DIR / "boundaries"

# geoBoundaries raw GitHub URLs (gbOpen release branch). If a release hash
# changes, browse https://www.geoboundaries.org/countryDownloads.html for
# the current Nigeria ADM0/ADM1/ADM2 links.
GEOBOUNDARIES_URLS = {
    "ADM0": "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/NGA/ADM0/geoBoundaries-NGA-ADM0.geojson",
    "ADM1": "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/NGA/ADM1/geoBoundaries-NGA-ADM1.geojson",
    "ADM2": "https://github.com/wmgeolab/geoBoundaries/raw/main/releaseData/gbOpen/NGA/ADM2/geoBoundaries-NGA-ADM2.geojson",
}


def download_boundary(level: str, out_dir: Path = BOUNDARIES_OUT_DIR) -> Path | None:
    if level not in GEOBOUNDARIES_URLS:
        raise ValueError(f"level must be one of {list(GEOBOUNDARIES_URLS)}")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"NGA_{level}.geojson"
    if out_path.exists():
        log.info("Already have %s, skipping", out_path.name)
        return out_path

    url = GEOBOUNDARIES_URLS[level]
    log.info("Downloading %s", url)
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    out_path.write_bytes(resp.content)
    log.info("Saved %s", out_path)
    return out_path


def download_all_boundaries() -> list[Path]:
    return [p for level in GEOBOUNDARIES_URLS for p in [download_boundary(level)] if p]


def filter_pilot_lgas(adm2_path: Path) -> "geopandas.GeoDataFrame":  # noqa: F821
    """Load ADM2 and filter to the three pilot LGAs. Lazily imports geopandas
    so this module can be used for download-only without the geo stack."""
    import geopandas as gpd

    from floodsight.config import AOI_LGAS

    gdf = gpd.read_file(adm2_path)
    name_col = "shapeName" if "shapeName" in gdf.columns else "shapeName1"
    mask = gdf[name_col].str.contains("|".join(AOI_LGAS), case=False, na=False)
    return gdf[mask]


if __name__ == "__main__":
    download_all_boundaries()
