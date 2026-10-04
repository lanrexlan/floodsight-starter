"""Serve prebuilt map files or cached bytes, bypassing slow per-request JSON encoding."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path

from fastapi import Request
from fastapi.responses import Response, FileResponse
from floodsight.config import PROCESSED_DIR

ASSETS_DIR = PROCESSED_DIR / "web"


def prepared_asset(name: str) -> Path | None:
    path = ASSETS_DIR / f"{name}.json"
    if not path.exists():
        return None
    # A rebuilt data source must never continue serving stale web geometry.
    from api.data_provider import SCORED_GRID_PATH, STREETS_RISK_PATH
    source = SCORED_GRID_PATH if name == "grid" else STREETS_RISK_PATH
    if source.exists() and source.stat().st_mtime > path.stat().st_mtime:
        return None
    return path


@lru_cache(maxsize=2)
def encoded_map(name: str) -> bytes:
    from api.data_provider import get_grid_geojson, get_streets_geojson
    data, _ = get_grid_geojson() if name == "grid" else get_streets_geojson()
    return json.dumps(data, separators=(",", ":"), allow_nan=False).encode()


def map_response(name: str, request: Request):
    path = prepared_asset(name)
    headers = {"Cache-Control": "public, max-age=3600", "Vary": "Accept-Encoding"}
    if path is not None:
        zipped = path.with_suffix(".json.gz")
        if "gzip" in request.headers.get("accept-encoding", "") and zipped.exists():
            path = zipped
            headers["Content-Encoding"] = "gzip"
        return FileResponse(path, media_type="application/geo+json", headers=headers)
    data = encoded_map(name)
    etag = '"' + hashlib.sha256(data).hexdigest() + '"'
    headers["ETag"] = etag
    if request.headers.get("if-none-match") == etag:
        return Response(status_code=304, headers=headers)
    return Response(data, media_type="application/geo+json", headers=headers)
