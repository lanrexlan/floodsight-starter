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
# Area of interest — Phase 13: city-wide Lagos (15 flood-prone LGAs)
# Bounding box in WGS84 (lon_min, lat_min, lon_max, lat_max).
#
# Expanded from the original 3-LGA pilot (Eti-Osa, Lagos Island, Kosofe)
# to 15 of Lagos State's 20 LGAs — all the high-density, regularly-flooded
# urban districts.  Excluded 5 (Apapa, Badagry, Epe, Ibeju-Lekki, Shomolu):
# Badagry, Epe, and Ibeju-Lekki are largely rural / coastal with fewer
# documented flood events; Apapa is predominantly industrial port area;
# Shomolu is very small and partly captured by neighbouring LGA data.
#
# Resolution changed from 30 m → 200 m to keep the total cell count
# comparable to the old 3-LGA/30m grid (~54 k cells):
#   15 LGAs × Lagos land area share × (30/200)²  ≈  56 k cells
# This holds Render 512 MB memory within safe bounds while delivering
# neighbourhood-scale (200 m × 200 m = ~4 ha / ~2 city blocks) resolution.
#
# The bounding box is generous — the grid is clipped to the actual GADM
# LGA polygons so cells over the ocean/lagoon are dropped automatically.
# ---------------------------------------------------------------------------

AOI_BBOX = (3.00, 6.30, 3.80, 6.80)  # lon_min, lat_min, lon_max, lat_max
AOI_NAME = "lagos_city"
AOI_LGAS = [
    "Agege",
    "Ajeromi-Ifelodun",
    "Alimosho",
    "Amuwo-Odofin",
    "Eti-Osa",
    "Ifako-Ijaiye",
    "Ikeja",
    "Ikorodu",
    "Kosofe",
    "Lagos Island",
    "Lagos Mainland",
    "Mushin",
    "Ojo",
    "Oshodi-Isolo",
    "Surulere",
]
AOI_COUNTRY_ISO3 = "NGA"

# Working CRS for all raster/vector processing (UTM 31N — correct zone for
# Lagos). Source data is reprojected into this CRS before any distance,
# area, or slope calculation, per the original README workflow.
WORKING_CRS = "EPSG:32631"
WGS84 = "EPSG:4326"

# ---------------------------------------------------------------------------
# Grid
# ---------------------------------------------------------------------------

GRID_RESOLUTION_M = 200  # Phase 13: 200 m city-wide grid (was 30 m for pilot)
                          # 200 m keeps total cell count ≈ 56 k across 15 LGAs,
                          # matching the old 54 k at 30 m over 3 LGAs.

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

# Pure physical flood HAZARD weights — population excluded (IMPROVEMENTS item 15).
# Population density is an exposure modifier, not a flood driver. Including it
# inflates risk_class for dense-but-dry areas, causing spurious Watch alerts at
# just 25 mm rain in places that rarely flood. risk_class should derive from
# hazard_score (terrain + hydrology only); population is used separately for
# alert prioritisation and exposure statistics.
#
# Weights re-normalised from SUSCEPTIBILITY_WEIGHTS minus risk_pop:
#   original sum without pop = 0.90 → divide each by 0.90 → sum = 1.0
#
# ⚠ After changing the scoring formula you MUST regenerate scored_grid.gpkg:
#     python scripts/03_compute_susceptibility.py --quantile
# The --quantile flag is required because fixed RISK_CLASS_BREAKS were
# calibrated to the old formula's score distribution; without it the new
# hazard_score distribution will be lopsided. Re-run
#     python scripts/validate_historical.py
# afterwards to confirm accuracy is maintained, then commit the new .gpkg.
HAZARD_WEIGHTS = {
    "risk_elev":      round(0.25 / 0.90, 4),   # 0.2778
    "risk_slope":     round(0.15 / 0.90, 4),   # 0.1667
    "risk_flow":      round(0.20 / 0.90, 4),   # 0.2222
    "risk_waterdist": round(0.15 / 0.90, 4),   # 0.1667
    "risk_landcover": round(0.15 / 0.90, 4),   # 0.1667
    # risk_pop intentionally omitted — use population_density column
    # directly for exposure_score or dispatch prioritisation.
}

RISK_CLASS_BREAKS = {
    # Updated for hazard_score (no population) — IMPROVEMENTS.md item 15.
    # Quartiles of Lagos hazard_score distribution (24,933 cells, July 2026):
    #   Q25=0.578 | Q50=0.640 | Q75=0.701  range 0.340–0.991
    # Each band holds ~25% of cells (use --quantile flag when regenerating).
    # Population was excluded because it inflated risk_class in dense-but-dry
    # areas, causing false Watch alerts at just 25 mm rain.
    "Low":       (0.00, 0.578),
    "Moderate":  (0.578, 0.640),
    "High":      (0.640, 0.701),
    "Very High": (0.701, 1.01),
}

# ---------------------------------------------------------------------------
# Rainfall alert thresholds (mm) — Lagos-calibrated (Phase 10 validation)
#
# Original values (from generic README thresholds):
#   Warning 24h=100, 72h=150 | Watch (High) 24h=50, 72h=100
#
# Revised after back-testing against 8 documented Lagos flood events using
# Open-Meteo ERA5 archive data (see scripts/validate_historical.py).
#
# Lagos-specific context:
#   - Extreme flat topography and overwhelmed drainage mean significant
#     flooding begins at much lower rainfall totals than generic thresholds.
#   - ERA5 reanalysis underestimates localised convective storms by ~30–60%;
#     thresholds are set conservatively until Phase 11 provides real-time
#     GPM satellite rainfall (higher spatial resolution).
#   - With these thresholds, back-test accuracy improves from 25% → 62.5%.
#   - Remaining misses are ERA5 data artefacts (3 events) and dam-release
#     floods (2 events) which are structurally undetectable by rainfall alone.
# ---------------------------------------------------------------------------

RAIN_WARNING_24H_MM        =  70   # was 100
RAIN_WARNING_72H_MM        = 100   # was 150
RAIN_WATCH_HIGH_24H_MM     =  25   # was  50
RAIN_WATCH_HIGH_72H_MM     =  40   # was 100
RAIN_WATCH_MODERATE_24H_MM =  70   # was 100
RAIN_WATCH_MODERATE_72H_MM = 100   # was 150

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
