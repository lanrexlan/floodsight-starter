"""
Central configuration for FloodSight.

Edit AOI / paths / thresholds here. Everything else in the codebase
reads from this module rather than hardcoding values, so this is the
one file you touch to retarget the whole pipeline at a new city.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# Load .env into the process environment. Without this call, every
# os.getenv() below silently returns None even with a correctly filled
# .env file sitting right next to it — python-dotenv only reads .env
# files when explicitly told to.
#
# interpolate=False is deliberate: python-dotenv performs shell-style
# $VAR / ${VAR} expansion by default, and does so for BOTH unquoted and
# double-quoted values (only single-quoted values skip it). A password
# or API key containing a literal "$" gets silently mangled by this —
# dotenv tries to substitute whatever follows the $ as a variable
# reference, usually into an empty string, with no error. Since nothing
# in this project's .env actually needs variable expansion, turning it
# off entirely removes that whole class of silent-credential-corruption
# bugs rather than relying on every secret being quoted "correctly."
load_dotenv(interpolate=False)

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------

ROOT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"
MODELS_DIR = DATA_DIR / "models"

for _d in (RAW_DIR, PROCESSED_DIR, MODELS_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Area of interest — Lagos pilot LGAs (Eti-Osa, Lagos Island, Kosofe)
# Bounding box in WGS84 (lon_min, lat_min, lon_max, lat_max).
# This is a generous box covering the three LGAs; tighten it with your
# actual ADM2 boundary geometry once boundaries.py has downloaded it
# (see floodsight/processing/grid.py, which clips to the real polygon).
# ---------------------------------------------------------------------------

AOI_BBOX = (3.30, 6.40, 3.62, 6.62)  # lon_min, lat_min, lon_max, lat_max
AOI_NAME = "lagos_pilot"
AOI_LGAS = ["Eti-Osa", "Lagos Island", "Kosofe"]
AOI_COUNTRY_ISO3 = "NGA"

# Working CRS for all raster/vector processing (UTM 31N — correct zone for
# Lagos). Source data is reprojected into this CRS before any distance,
# area, or slope calculation, per the original README workflow.
WORKING_CRS = "EPSG:32631"
WGS84 = "EPSG:4326"

# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

GRID_RESOLUTION_M = 30  # matches the existing 30m pilot grid

# ---------------------------------------------------------------------------
# Susceptibility model (v0 — ported from the existing README formula)
# flood_score = sum(weight_i * normalized_risk_factor_i)
# ---------------------------------------------------------------------------

SUSCEPTIBILITY_WEIGHTS = {
    "risk_elev": 0.25,
    "risk_slope": 0.15,
    "risk_flow": 0.20,
    "risk_waterdist": 0.15,
    "risk_landcover": 0.15,
    "risk_pop": 0.10,
}

RISK_CLASS_BREAKS = {
    "Low": (0.0, 0.25),
    "Moderate": (0.25, 0.50),
    "High": (0.50, 0.75),
    "Very High": (0.75, 1.01),  # upper bound inclusive of 1.0
}

# ---------------------------------------------------------------------------
# Rainfall alert thresholds (mm) — ported from the existing README logic
# ---------------------------------------------------------------------------

RAIN_WARNING_24H_MM = 100
RAIN_WARNING_72H_MM = 150
RAIN_WATCH_HIGH_24H_MM = 50
RAIN_WATCH_HIGH_72H_MM = 100
RAIN_WATCH_MODERATE_24H_MM = 100
RAIN_WATCH_MODERATE_72H_MM = 150

# ---------------------------------------------------------------------------
# HAND-based depth model (Track A — see ROADMAP.md Phase 1)
# ---------------------------------------------------------------------------

HAND_BIN_COUNT = 25  # number of HAND elevation bins used to build the
                      # synthetic rating curve per drainage reach

# ---------------------------------------------------------------------------
# ML model
# ---------------------------------------------------------------------------

ML_FEATURE_COLUMNS = [
    "elevation_m",
    "slope_deg",
    "flow_accum",
    "hand_m",
    "dist_to_water_m",
    "landcover_class",
    "population_density",
    "rain_24h_mm",
    "rain_72h_mm",
]
ML_TARGET_COLUMN = "depth_m"
ML_MODEL_PATH = MODELS_DIR / "depth_model.joblib"

# ---------------------------------------------------------------------------
# External service credentials (read from environment / .env)
# ---------------------------------------------------------------------------


@dataclass
class Credentials:
    nasa_earthdata_username: str | None = field(
        default_factory=lambda: os.getenv("NASA_EARTHDATA_USERNAME")
    )
    nasa_earthdata_password: str | None = field(
        default_factory=lambda: os.getenv("NASA_EARTHDATA_PASSWORD")
    )
    cds_api_key: str | None = field(default_factory=lambda: os.getenv("CDS_API_KEY"))
    africastalking_username: str | None = field(
        default_factory=lambda: os.getenv("AFRICASTALKING_USERNAME")
    )
    africastalking_api_key: str | None = field(
        default_factory=lambda: os.getenv("AFRICASTALKING_API_KEY")
    )


CREDENTIALS = Credentials()

# earthaccess's strategy="environment" login specifically requires the
# env vars to be named EARTHDATA_USERNAME / EARTHDATA_PASSWORD — not the
# NASA_EARTHDATA_* names used in .env, which exist only for clarity in
# this project's own .env file. Mirror them across here so .env doesn't
# need to duplicate values under two different names, and so earthaccess
# actually finds them.
if CREDENTIALS.nasa_earthdata_username and CREDENTIALS.nasa_earthdata_password:
    os.environ.setdefault("EARTHDATA_USERNAME", CREDENTIALS.nasa_earthdata_username)
    os.environ.setdefault("EARTHDATA_PASSWORD", CREDENTIALS.nasa_earthdata_password)
