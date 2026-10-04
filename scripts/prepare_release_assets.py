"""Build compact, compressed maps during deployment, never on the first visitor."""
import gzip
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from api.assets import ASSETS_DIR
from api.data_provider import get_grid_geojson, get_streets_geojson
from floodsight.config import GRID_RESOLUTION_M, RISK_CLASS_BREAKS


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--layer', choices=['all','grid','streets'], default='all')
    args = parser.parse_args()
    ASSETS_DIR.mkdir(parents=True, exist_ok=True)
    for name, loader in (("grid", get_grid_geojson), ("streets", get_streets_geojson)):
        if args.layer not in ('all', name):
            continue
        data, source = loader()
        if data is None:
            print(f"{name}: unavailable (optional layer disabled)")
            continue
        if name == 'grid':
            from api.data_provider import get_grid, SCORED_GRID_PATH
            import hashlib
            grid, _ = get_grid()
            if 'lga_name' in grid and SCORED_GRID_PATH.exists():
                cells = {str(row.cell_id): row.lga_name if isinstance(row.lga_name, str) else None for row in grid.itertuples()}
                index = {'source_sha256':hashlib.sha256(SCORED_GRID_PATH.read_bytes()).hexdigest(), 'cells':cells}
                (ASSETS_DIR.parent/'lga_index.json').write_text(json.dumps(index, separators=(',',':'), sort_keys=True), encoding='utf-8')
        data["metadata"] = {"resolution_m": GRID_RESOLUTION_M,
                            "risk_breaks": RISK_CLASS_BREAKS,
                            "source": source, "stage": "controlled_pilot"}
        payload = json.dumps(data, separators=(",", ":"), allow_nan=False).encode()
        (ASSETS_DIR / f"{name}.json").write_bytes(payload)
        compressed = gzip.compress(payload, compresslevel=6, mtime=0)
        (ASSETS_DIR / f"{name}.json.gz").write_bytes(compressed)
        print(f"{name}: {len(data['features'])} features, {len(payload):,} bytes, {len(compressed):,} gzip bytes")
        if name == "streets":
            from api.street_tiles import build_tiles
            build_tiles(data)


if __name__ == "__main__":
    main()
