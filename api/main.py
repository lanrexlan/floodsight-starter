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

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from api.routers import alerts, depth, dispatch, forecast, risk, subscribe, validate, verify

app = FastAPI(
    title="FloodSight API",
    description="Flood susceptibility, depth prediction, and alert API for the Lagos pilot.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten this once you have a fixed deployed
                           # frontend origin to allow specifically
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(risk.router)
app.include_router(depth.router)
app.include_router(alerts.router)
app.include_router(verify.router)
app.include_router(forecast.router)
app.include_router(validate.router)
app.include_router(subscribe.router)
app.include_router(dispatch.router)


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
            "/alerts/dispatch",
            "/depth/predict",
            "/alerts/current",
            "/verify", "/verify/summary",
            "/forecast/rainfall", "/forecast/alerts", "/forecast/summary",
            "/validate/events",
        ],
    }


@app.get("/health")
def health():
    return {"status": "ok"}


# Mounted at /dashboard (not /) so it can't shadow the API status route
# above or any /risk, /depth, /alerts route — StaticFiles with html=True
# automatically serves dashboard/index.html for /dashboard/ itself.
DASHBOARD_DIR = Path(__file__).resolve().parent.parent / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/dashboard", StaticFiles(directory=DASHBOARD_DIR, html=True), name="dashboard")
