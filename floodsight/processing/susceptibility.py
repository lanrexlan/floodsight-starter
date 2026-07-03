"""
Flood susceptibility scoring — a direct port of the existing repo's
README formula, kept as the v0 baseline layer (fast, explainable,
zero training data required) that both the dashboard and the HAND depth
model (depth_hand.py) can fall back on or cross-check against.

flood_score = 0.25*risk_elev + 0.15*risk_slope + 0.20*risk_flow
            + 0.15*risk_waterdist + 0.15*risk_landcover + 0.10*risk_pop

NOTE on the skew flagged in the roadmap doc: normalization here is
min-max per factor over the AOI. If your risk_class distribution comes
out lopsided again (almost everything Moderate/High, almost nothing Low
or Very High), check the actual histogram of `flood_score` with
`df.flood_score.describe()` / `df.flood_score.hist()` before trusting
the breakpoints in floodsight/config.py — they may need to be set from
quantiles of your specific AOI rather than the fixed 0.25/0.50/0.75
defaults.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from floodsight.config import RISK_CLASS_BREAKS, SUSCEPTIBILITY_WEIGHTS

logging.basicConfig(level=logging.INFO)
log = logging.getLogger(__name__)


def _normalize(series: pd.Series, higher_is_riskier: bool) -> pd.Series:
    """Min-max normalize to [0, 1]. If higher raw values mean *lower*
    risk (e.g. elevation, distance to water), the series is inverted
    first so that 1.0 always means 'most risky' after normalization."""
    s = series.astype(float)
    if not higher_is_riskier:
        s = -s
    s_min, s_max = s.min(), s.max()
    if s_max - s_min == 0:
        return pd.Series(np.zeros(len(s)), index=s.index)
    return (s - s_min) / (s_max - s_min)


# Land cover risk lookup, keyed by ESA WorldCover class codes.
# https://esa-worldcover.org/en — class values used in the v200 product.
LANDCOVER_RISK = {
    10: 0.5,   # Tree cover — moderate (can slow but also channel flow)
    20: 0.4,   # Shrubland
    30: 0.5,   # Grassland
    40: 0.6,   # Cropland
    50: 0.9,   # Built-up — high (impervious surfaces, poor infiltration)
    60: 0.4,   # Bare / sparse vegetation
    70: 0.2,   # Snow and ice (not relevant in Lagos, included for completeness)
    80: 1.0,   # Permanent water bodies — already inundated
    90: 0.95,  # Herbaceous wetland — very high
    95: 0.9,   # Mangroves — very high (tidal/coastal flood exposure)
    100: 0.5,  # Moss and lichen
}


def compute_flood_score(df: pd.DataFrame, use_quantile_breaks: bool = False) -> pd.DataFrame:
    """
    df must have columns: elevation_m, slope_deg, flow_accum,
    dist_to_water_m, landcover_class, population_density.
    Returns df with risk_elev..risk_pop, flood_score, and risk_class added.

    use_quantile_breaks: if True, risk_class is assigned by quartile of
    the AOI's own flood_score distribution (each class ~25% of scored
    cells) instead of the fixed 0.25/0.50/0.75 breakpoints in
    RISK_CLASS_BREAKS. Use this whenever the fixed breakpoints produce a
    lopsided distribution (e.g. almost everything landing in one class)
    — which is the normal case on real terrain, since flood
    susceptibility scores from a weighted overlay rarely spread evenly
    across 0-1. Quantile breaks always give you four classes with
    roughly equal cell counts, which is far more useful for triage even
    though the absolute score boundaries become AOI-specific rather than
    a fixed, comparable-across-cities scale. If you need both
    (comparability AND balanced classes), keep flood_score itself for
    comparison and treat risk_class as a local triage label only.

    If any factor column is entirely NaN (e.g. dist_to_water_m before
    you've run the OSM download), that factor is dropped and its weight
    is redistributed proportionally across the remaining factors, with a
    warning — rather than letting NaN silently propagate into
    flood_score for every cell, which would otherwise make every cell
    fall through _classify()'s fallback into "Very High". Rerun this
    once all factors are populated for real scores.
    """
    df = df.copy()

    candidates = {
        "risk_elev": (df["elevation_m"], False),
        "risk_slope": (df["slope_deg"], False),
        "risk_flow": (df["flow_accum"], True),
        "risk_waterdist": (df["dist_to_water_m"], False),
        "risk_pop": (df["population_density"], True),
    }

    active_weights = dict(SUSCEPTIBILITY_WEIGHTS)
    dropped = []
    for factor, (series, higher_is_riskier) in candidates.items():
        if series.isna().all():
            dropped.append(factor)
            active_weights.pop(factor, None)
            df[factor] = 0.0
        else:
            df[factor] = _normalize(series, higher_is_riskier=higher_is_riskier)

    df["risk_landcover"] = df["landcover_class"].map(LANDCOVER_RISK).fillna(0.5)
    if "risk_landcover" not in active_weights:
        active_weights["risk_landcover"] = SUSCEPTIBILITY_WEIGHTS["risk_landcover"]

    if dropped:
        weight_total = sum(active_weights.values())
        active_weights = {k: w / weight_total for k, w in active_weights.items()}
        log.warning(
            "Dropping factor(s) %s — entirely missing data — and "
            "reweighting the rest proportionally: %s. Scores below are "
            "INCOMPLETE until you rerun with full feature data.",
            dropped,
            {k: round(v, 3) for k, v in active_weights.items()},
        )

    df["flood_score"] = sum(df[factor] * weight for factor, weight in active_weights.items())

    if use_quantile_breaks:
        df["risk_class"] = _classify_quantile(df["flood_score"])
        log.info(
            "Using QUANTILE-based risk classes (each class ~25%% of "
            "scored cells, boundaries specific to this AOI's score "
            "distribution, not comparable across cities)."
        )
    else:
        df["risk_class"] = df["flood_score"].apply(_classify)

    log.info("Risk class distribution:\n%s", df["risk_class"].value_counts())
    return df


def _classify_quantile(flood_score: pd.Series) -> pd.Series:
    """Assign risk_class by quartile of the scored (non-NaN) cells, so
    each class gets roughly equal representation regardless of how
    tightly clustered the raw scores are. NaN scores (e.g. cells outside
    raster coverage) stay "Unknown" rather than being silently dropped
    from the quartile computation or misclassified."""
    valid = flood_score.dropna()
    if valid.empty:
        return pd.Series(["Unknown"] * len(flood_score), index=flood_score.index)

    labels = ["Low", "Moderate", "High", "Very High"]
    try:
        classed = pd.qcut(valid, q=4, labels=labels, duplicates="drop")
    except ValueError:
        # Not enough distinct values to form 4 quantile bins (e.g. a
        # tiny or degenerate AOI) — fall back to the fixed breaks rather
        # than failing outright.
        log.warning(
            "Not enough distinct flood_score values for quartile "
            "classification — falling back to fixed RISK_CLASS_BREAKS."
        )
        return flood_score.apply(_classify)

    result = pd.Series(["Unknown"] * len(flood_score), index=flood_score.index, dtype=object)
    result.loc[classed.index] = classed.astype(str)
    return result


def _classify(score: float) -> str:
    if pd.isna(score):
        return "Unknown"
    for cls, (lo, hi) in RISK_CLASS_BREAKS.items():
        if lo <= score < hi:
            return cls
    return "Very High"  # score == 1.0 edge case
