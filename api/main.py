"""
FloodSight API.

Run locally:
    uvicorn api.main:app --reload --port 8000

Then open http://localhost:8000/docs for interactive API docs, or open
dashboard/index.html directly in a browser for local development (it
auto-detects local file:// access and points at http://localhost:8000 —
see dashboard/app.js API_BASE_URL).

In a real deployment (e.g. Render), this same app also serves the
dashboard itself at /dashboard/ — one service, one URL, no CORS
complexity between a separately-hosted frontend and backend.

Works out of the box with a synthetic demo grid even before you've run
any of the data download/processing scripts — see api/data_provider.py.
"""

from __future__ import annotations

import logging
import os
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.gzip import GZipMiddleware
from api.security import RequestProtection

from api.routers import alerts, depth, dispatch, forecast, health, incoming, risk, subscribe, validate, verify

log = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Pre-warm the grid GeoJSON cache at startup.

    Without this, the first dashboard visitor after a cold start (Render
    free-tier spin-up, or a new deploy) triggers a synchronous 9 MB GPKG
    load + 24,933-cell WGS84 reproject + JSON serialisation.  On the 512 MB
    free tier that takes 15–30 s and appears as a blank map or 502.

    We spin a daemon thread so startup is non-blocking — Render's health
    check passes immediately and requests are accepted while the cache is
    still warming.  Subsequent requests block on the cached copy (< 1 ms).
    """
    from api.release import startup_errors
    errors = startup_errors()
    if errors:
        raise RuntimeError("Production configuration incomplete: " + "; ".join(errors))
    # Report missing configuration before anything else. Several subsystems
    # fail closed when an env var is unset (notably AT_WEBHOOK_TOKEN, which
    # makes every inbound-SMS callback return 503), and a closed failure with
    # no signal looks exactly like a quiet day. Logging at startup means the
    # operator sees it in Render's log view without going looking.
    try:
        from api.diagnostics import log_config_report
        log_config_report()
    except Exception as exc:
        log.warning("Config diagnostics failed (non-fatal): %s", exc)

    def _warm():
        try:
            from api.assets import prepared_asset
            if prepared_asset("grid") is not None:
                return
            from api.data_provider import get_grid_geojson
            get_grid_geojson()
            log.info("Startup warmup complete — grid GeoJSON cached.")
        except Exception as exc:
            log.warning("Startup warmup failed (non-fatal): %s", exc)

    threading.Thread(target=_warm, daemon=True, name="cache-warmup").start()
    yield  # app runs


app = FastAPI(
    title="FloodSight API",
    description="Flood susceptibility, depth prediction, and alert API for the Lagos pilot.",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[s.strip() for s in os.getenv("CORS_ORIGINS", "http://localhost:8000,http://127.0.0.1:8000").split(",") if s.strip()],
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["Content-Type", "Authorization"],
)
app.add_middleware(GZipMiddleware, minimum_size=1000, compresslevel=5)
app.add_middleware(RequestProtection)

app.include_router(risk.router)
app.include_router(depth.router)
app.include_router(alerts.router)
app.include_router(verify.router)
app.include_router(forecast.router)
app.include_router(validate.router)
app.include_router(subscribe.router)
app.include_router(dispatch.router)
app.include_router(incoming.router)
app.include_router(health.router)
from api.routers import places
app.include_router(places.router)


@app.get("/ready")
def readiness():
    from api.release import readiness_report
    report = readiness_report()
    return JSONResponse(report, status_code=200 if report["ready"] else 503)


@app.get("/product-status")
def product_status():
    from floodsight.config import AOI_BBOX, GRID_RESOLUTION_M, RISK_CLASS_BREAKS
    from floodsight import config
    from api.runtime import production
    return {"stage": "controlled_pilot", "coverage_bbox": AOI_BBOX,
            "grid_resolution_m": GRID_RESOLUTION_M, "risk_breaks": RISK_CLASS_BREAKS,
            "depth_model": "experimental", "official_emergency_service": False,
            "experimental_depth_enabled": not production() or os.getenv("ENABLE_EXPERIMENTAL_DEPTH", "false").lower() == "true",
            "alert_thresholds": {"WARNING_24H": config.RAIN_WARNING_24H_MM,
                "WARNING_72H": config.RAIN_WARNING_72H_MM,
                "WATCH_HIGH_24H": config.RAIN_WATCH_HIGH_24H_MM,
                "WATCH_HIGH_72H": config.RAIN_WATCH_HIGH_72H_MM,
                "WATCH_MOD_24H": config.RAIN_WATCH_MODERATE_24H_MM,
                "WATCH_MOD_72H": config.RAIN_WATCH_MODERATE_72H_MM},
            "advisory": "No Alert means no threshold exceeded, not a guarantee that flooding will not occur."}


@app.get("/floodsight.html", include_in_schema=False)
def landing_page():
    return FileResponse(Path(__file__).resolve().parent.parent / "floodsight.html")


@app.get("/privacy.html", include_in_schema=False)
@app.get("/dashboard/privacy.html", include_in_schema=False)
def privacy_page():
    return FileResponse(Path(__file__).resolve().parent.parent / "privacy.html")


@app.get("/diagnostics")
def diagnostics():
    """
    Configuration health check for the operator dashboard.

    Reports which required environment variables are unset and, for each, the
    user-facing capability that is consequently switched off. Returns only
    whether a name is set — never a secret value — so it is safe to expose
    alongside the other public status routes.

    ``status`` is ``"degraded"`` when any required variable is missing.
    """
    from api.diagnostics import config_report
    return config_report()


@app.get("/")
def root():
    return {
        "service": "FloodSight API",
        "status": "ok",
        "docs": "/docs",
        "dashboard": "/dashboard/",
        "endpoints": [
            "/risk/grid", "/risk/point", "/risk/streets",
            "/subscribe", "/subscribers/count",
            "/subscribers/stats", "/alerts/history",
            "/alerts/dispatch",
            "/depth/predict", "/depth/ml-grid", "/depth/ml-grid/summary",
            "/alerts/current",
            "/verify", "/verify/summary",
            "/health/risk", "/health/chew-response", "/health/mel/summary", "/health/mel/operational",
            "/at/incoming", "/at/delivery", "/subscribe/confirm",
            "/diagnostics",
            "/forecast/rainfall", "/forecast/alerts", "/forecast/summary",
            "/validate/events",
            "/health/risk", "/health/risk/{lga_name}",
            "/health/chew-response", "/health/mel/summary",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# Health dashboard must be mounted BEFORE /dashboard so FastAPI's prefix
# matching doesn't swallow /dashboard/health/* with the broader mount first.
HEALTH_DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard" / "health"
if HEALTH_DASHBOARD_DIR.exists():
    app.mount(
        "/dashboard/health",
        StaticFiles(directory=HEALTH_DASHBOARD_DIR, html=True),
        name="health-dashboard",
    )

# Main flood dashboard — mounted at /dashboard (not /) so it can't shadow
# the API routes above. StaticFiles with html=True serves index.html for
# /dashboard/ itself.
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
