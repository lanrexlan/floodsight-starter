"""
Download OpenStreetMap roads, buildings, and water bodies for Nigeria,
then clip to the AOI.

Source: Geofabrik regional extracts (updated daily, no account needed).
  https://download.geofabrik.de/africa/nigeria.html
  Full-country .osm.pbf, ~650MB+ — clip locally rather than re-downloading
  per-LGA.

After download, use `pyrosm` (pure Python, no GDAL OSM driver needed) to
extract roads/buildings/water directly from the .pbf clipped to the AOI
bounding box, which avoids loading the whole country into memory.

Usage:
    python -m floodsight.download.osm
"""

from __future__ import annotations

import logging
from pathlib import Path

import requests

from floodsight.config import AOI_BBOX, RAW_DIR

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

OSM_OUT_DIR = RAW_DIR / "osm"
GEOFABRIK_URL = "https://download.geofabrik.de/africa/nigeria-latest.osm.pbf"


def download_osm_pbf(out_dir: Path = OSM_OUT_DIR) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "nigeria-latest.osm.pbf"
    if out_path.exists():
        log.info("Already have %s, skipping", out_path.name)
        return out_path

    log.info("Downloading %s (this is a large file, several hundred MB)", GEOFABRIK_URL)
    resp = requests.get(GEOFABRIK_URL, stream=True, timeout=300)
    resp.raise_for_status()
    with open(out_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=1 << 20):
            f.write(chunk)
    log.info("Saved %s", out_path)
    return out_path


def extract_layers_for_aoi(
    pbf_path: Path, bbox: tuple[float, float, float, float] = AOI_BBOX
) -> dict[str, "geopandas.GeoDataFrame"]:  # noqa: F821
    """Extract roads, buildings, and water polygons clipped to bbox using
    pyrosm. Requires: pip install pyrosm"""
    from pyrosm import OSM

    osm = OSM(str(pbf_path), bounding_box=list(bbox))
    layers = {
        "roads": osm.get_network(network_type="driving"),
        "buildings": osm.get_buildings(),
        "water": osm.get_natural(extra_attributes=["water"]),
    }
    out_dir = OSM_OUT_DIR / "clipped"
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, gdf in layers.items():
        if gdf is not None and len(gdf):
            gdf.to_file(out_dir / f"{name}.gpkg", driver="GPKG")
            log.info("Saved %d %s features", len(gdf), name)
    return layers


if __name__ == "__main__":
    pbf = download_osm_pbf()
    extract_layers_for_aoi(pbf)
