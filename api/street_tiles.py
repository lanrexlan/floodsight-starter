"""Small prebuilt street windows for mobile maps; preserve original feature IDs."""
import json
import math
from functools import lru_cache
from pathlib import Path

from fastapi import HTTPException, Request
from fastapi.responses import Response
from api.assets import ASSETS_DIR
from floodsight.config import AOI_BBOX

ZOOM = 12


def tile_xy(lon, lat):
    n = 2**ZOOM
    return int((lon+180)/360*n), int((1-math.asinh(math.tan(math.radians(lat)))/math.pi)/2*n)


def tile_range(bounds):
    west, south, east, north = bounds
    xmin, ymin = tile_xy(west, north)
    xmax, ymax = tile_xy(east, south)
    return tuple((x,y) for x in range(xmin,xmax+1) for y in range(ymin,ymax+1))


def build_tiles(data):
    from shapely.geometry import shape
    groups = {}
    for feature in data['features']:
        for tile in tile_range(shape(feature['geometry']).bounds):
            groups.setdefault(tile, []).append(feature)
    destination = ASSETS_DIR / 'streets_tiles'
    destination.mkdir(parents=True, exist_ok=True)
    # Rebuilding must remove obsolete tiles, scoped to this generated directory.
    for path in destination.glob('*.json'):
        path.unlink()
    for (x,y), features in groups.items():
        (destination / f'{x}_{y}.json').write_text(json.dumps(features, separators=(',',':')), encoding='utf-8')
    print(f'streets: built {len(groups)} viewport tiles')


@lru_cache(maxsize=32)
def window_bytes(tiles):
    features = {}
    for x,y in tiles:
        path = ASSETS_DIR / 'streets_tiles' / f'{x}_{y}.json'
        if path.exists():
            for feature in json.loads(path.read_text(encoding='utf-8')):
                features[feature['id']] = feature
    return json.dumps({'type':'FeatureCollection', 'features':list(features.values()),
                       'data_source':'osm_risk_tagged', 'resolution_m':200}, separators=(',',':')).encode()


def street_window(bbox: str, request: Request):
    try:
        bounds = tuple(float(v) for v in bbox.split(','))
        if len(bounds) != 4 or not all(math.isfinite(v) for v in bounds):
            raise ValueError()
        west,south,east,north = bounds
        if not (-180 <= west < east <= 180 and -85 <= south < north <= 85):
            raise ValueError()
    except ValueError as exc:
        raise HTTPException(422,'bbox must be west,south,east,north in WGS84.') from exc
    aw,asouth,ae,an = AOI_BBOX
    clipped = (max(west,aw), max(south,asouth), min(east,ae), min(north,an))
    if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
        tiles = ()
    else:
        tiles = tile_range(clipped)
    if not (ASSETS_DIR/'streets_tiles').exists():
        raise HTTPException(503,'Street viewport assets are not prepared yet.')
    return Response(window_bytes(tiles), media_type='application/geo+json', headers={'Cache-Control':'public, max-age=3600'})
