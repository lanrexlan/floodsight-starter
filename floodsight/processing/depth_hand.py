"""
Convert river discharge into an actual flood depth-in-meters layer, using
a HAND-derived synthetic rating curve. This is "Track A" from
ROADMAP.md Phase 1 — the fast, physically-based path to a real depth
output that doesn't require a trained ML model or labeled data.

Method (synthetic rating curve from HAND hypsometry):
  For a candidate water-surface stage h (height above the drainage
  channel, in the same units as the HAND raster from terrain.py):
    1. flooded(h)   = cells where hand <= h
    2. avg_depth(h) = mean(h - hand) over flooded cells
    3. top_width(h) = flooded_planform_area(h) / characteristic_channel_length
    4. Using the wide-channel approximation (top_width >> depth, so the
       hydraulic radius R ~= avg_depth): apply Manning's equation
         Q(h) = (1/n) * A(h) * R(h)^(2/3) * sqrt(S)
       where A(h) = top_width(h) * avg_depth(h), S = representative
       channel slope, n = Manning's roughness coefficient.
  This builds a stage-discharge table; given an observed/forecast Q, we
  invert the table to get stage h, then depth per cell = max(0, h - hand).

IMPORTANT — this is a deliberate first-pass simplification: it treats
the whole AOI as a single hydraulic reach rather than delineating
individual sub-catchments/reaches and building a rating curve per reach
(the approach used in NOAA's production HAND-based inundation mapping,
https://github.com/NOAA-OWP/inundation-mapping). For a 3-LGA pilot area
this is a reasonable starting point; if depth outputs look implausible
at the catchment boundary once you have real discharge data, that's the
signal to move to per-reach rating curves.

Manning's n defaults below are standard textbook values (Chow, 1959) —
recalibrate against any local channel survey or historical
high-water-mark data you can get from SEMA/NiHSA once available.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)

# Manning's roughness coefficient (dimensionless). 0.035 = "clean, winding,
# some pools and shoals" natural channel — a reasonable default for Lagos
# lagoon-fringe drainage; lower it (e.g. 0.025) for engineered/concrete
# drains, raise it (e.g. 0.06-0.10) for heavily vegetated/wetland channels.
DEFAULT_MANNING_N = 0.035

# Representative channel slope (dimensionless, m/m). Measured from real
# Lagos pilot terrain (June 2026): mean slope across 1,506 grid cells
# with flow_accum > 500, within the 3-LGA AOI specifically (not a
# regional average) = 0.924 deg = 0.016135 m/m.
#
# CAVEAT — likely an overestimate of true ground slope: Copernicus DEM
# GLO-30 is a surface model (DSM), not a bare-earth terrain model (DTM)
# — its elevation values include building rooftops and canopy height,
# not just ground level. In dense built-up Lagos, channels running
# between buildings show artificially steep "cliffs" at building edges
# in the DSM that don't exist at actual ground/water level, which
# inflates any slope measured near them. Lagos's true ground slope along
# drainage is generally understood to be far flatter than this (closer
# to 0.0001-0.001 m/m) given its minimal coastal relief. Until a
# bare-earth DTM or a building-height correction (e.g. subtracting OSM
# building footprint heights from the DSM in built-up cells) is
# available, treat this value as an upper bound, not ground truth — see
# ROADMAP.md for this as a flagged follow-up.
DEFAULT_CHANNEL_SLOPE = 0.016135


def build_rating_curve(
    hand: np.ndarray,
    cell_size_m: float,
    channel_length_m: float,
    manning_n: float = DEFAULT_MANNING_N,
    channel_slope: float = DEFAULT_CHANNEL_SLOPE,
    max_stage_m: float = 6.0,
    n_stages: int = 60,
) -> pd.DataFrame:
    """Build a stage -> discharge table from the HAND raster's hypsometry.

    channel_length_m: total along-channel length of the drainage network
    within the AOI (sum of drainage-cell run lengths) — used to convert
    flooded planform area into an average top width. Estimate this from
    your flow-accumulation-derived stream network (e.g. count drainage
    cells * cell_size_m as a rough proxy if you haven't vectorized the
    network yet).
    """
    cell_area_m2 = cell_size_m**2
    stages = np.linspace(0.05, max_stage_m, n_stages)

    rows = []
    valid_hand = hand[~np.isnan(hand)]
    for h in stages:
        flooded = valid_hand <= h
        if not flooded.any():
            continue
        avg_depth = float(np.mean(h - valid_hand[flooded]))
        planform_area = float(flooded.sum()) * cell_area_m2
        top_width = max(planform_area / channel_length_m, 1.0)  # avoid div-by-zero

        cross_section_area = top_width * avg_depth
        hydraulic_radius = avg_depth  # wide-channel approximation, R ~= depth
        discharge = (
            (1.0 / manning_n)
            * cross_section_area
            * hydraulic_radius ** (2.0 / 3.0)
            * np.sqrt(channel_slope)
        )
        rows.append(
            {
                "stage_m": h,
                "avg_depth_m": avg_depth,
                "top_width_m": top_width,
                "discharge_cms": discharge,
            }
        )

    curve = pd.DataFrame(rows)
    log.info(
        "Built rating curve: stage 0-%.1fm -> discharge %.1f-%.1f m3/s",
        max_stage_m,
        curve["discharge_cms"].min(),
        curve["discharge_cms"].max(),
    )
    return curve


def stage_for_discharge(rating_curve: pd.DataFrame, discharge_cms: float) -> float:
    """Invert the rating curve via linear interpolation to find the stage
    (meters above drainage) corresponding to an observed/forecast discharge."""
    if discharge_cms <= rating_curve["discharge_cms"].min():
        return float(rating_curve["stage_m"].min())
    if discharge_cms >= rating_curve["discharge_cms"].max():
        log.warning(
            "Requested discharge %.1f m3/s exceeds rating curve max (%.1f) — "
            "extrapolating linearly past the curve, treat this depth output "
            "with extra caution and consider raising max_stage_m.",
            discharge_cms,
            rating_curve["discharge_cms"].max(),
        )
    return float(
        np.interp(discharge_cms, rating_curve["discharge_cms"], rating_curve["stage_m"])
    )


def discharge_to_depth_raster(
    hand: np.ndarray, rating_curve: pd.DataFrame, discharge_cms: float
) -> np.ndarray:
    """The final step: given a discharge value (from GloFAS or a
    rainfall-runoff estimate), return a depth-in-meters array aligned to
    the HAND grid."""
    stage = stage_for_discharge(rating_curve, discharge_cms)
    depth = np.clip(stage - hand, 0, None)
    depth = np.nan_to_num(depth, nan=0.0)
    log.info(
        "Discharge %.1f m3/s -> stage %.2fm -> max depth %.2fm, %d cells flooded",
        discharge_cms,
        stage,
        float(depth.max()),
        int((depth > 0).sum()),
    )
    return depth


def rainfall_to_discharge_scs(
    rain_24h_mm: float, catchment_area_km2: float, curve_number: int = 85
) -> float:
    """
    Fallback discharge estimate from rainfall when GloFAS discharge isn't
    available for the AOI's small urban drainage scale (GloFAS resolution
    is often too coarse for Lagos's local creeks). Uses the standard SCS
    Curve Number method for runoff depth, then a simple triangular
    unit-hydrograph peak-flow approximation.

    curve_number: SCS-CN, 0-100. 85 is typical for "urban, mostly
    impervious" — appropriate for built-up Lagos Island/Eti-Osa; lower it
    (e.g. 70-75) for more vegetated/permeable parts of Kosofe. Calibrate
    against land cover mix once you've sampled landcover_class onto the
    grid (see processing/features.py).
    """
    s = (25400.0 / curve_number) - 254.0  # potential max retention, mm
    initial_abstraction = 0.2 * s
    if rain_24h_mm <= initial_abstraction:
        return 0.0
    runoff_mm = (rain_24h_mm - initial_abstraction) ** 2 / (
        rain_24h_mm - initial_abstraction + s
    )
    runoff_volume_m3 = runoff_mm / 1000.0 * catchment_area_km2 * 1e6
    # Triangular unit hydrograph approximation: assume the runoff volume
    # drains over a ~6-hour event window for a small flat urban catchment.
    event_duration_s = 6 * 3600
    peak_discharge_cms = (2.0 * runoff_volume_m3) / event_duration_s
    return float(peak_discharge_cms)
