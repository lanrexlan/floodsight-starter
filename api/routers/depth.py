from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, Request, Depends

from api.auth import require_dispatch_secret
from api.schemas import DepthPredictionRequest, DepthPredictionResponse
from floodsight.config import DATA_DIR, ML_MODEL_PATH

router = APIRouter(prefix="/depth", tags=["depth"])
log = logging.getLogger(__name__)

LOGS_DIR = DATA_DIR / "logs"
PREDICTIONS_LOG = LOGS_DIR / "predictions.jsonl"


def _log_prediction(req: DepthPredictionRequest, predicted_depth_m: float) -> None:
    """
    Persist one prediction (fire-and-forget, non-fatal).

    Writes to Supabase (survives Render deploys/restarts); falls back to a
    local JSONL file when Supabase is not configured (local dev only —
    Render's disk is ephemeral, so the JSONL fallback is NOT durable there).
    """
    try:
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "lat": req.lat,
            "lon": req.lon,
            "cell_id": req.cell_id,
            "features": {
                "elevation_m": req.elevation_m,
                "slope_deg": req.slope_deg,
                "flow_accum": req.flow_accum,
                "hand_m": req.hand_m,
                "dist_to_water_m": req.dist_to_water_m,
                "landcover_class": req.landcover_class,
                "population_density": req.population_density,
                "rain_24h_mm": req.rain_24h_mm,
                "rain_72h_mm": req.rain_72h_mm,
            },
            "predicted_depth_m": predicted_depth_m,
        }
        try:
            from floodsight.db.supabase_client import log_prediction

            log_prediction(entry)
            return
        except RuntimeError:
            pass  # Supabase not configured — local JSONL fallback below
        except Exception as exc:
            log.warning("Supabase prediction log failed (%s) — JSONL fallback", exc)

        from api.runtime import production
        if production():
            log.error("Prediction audit storage unavailable; no ephemeral PII fallback in production.")
            return
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(PREDICTIONS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:  # never crash the API over logging
        log.warning("Failed to write prediction log: %s", exc)


@router.post("/predict", response_model=DepthPredictionResponse)
def predict_depth(req: DepthPredictionRequest):
    from api.runtime import experimental_depth_enabled
    if not experimental_depth_enabled():
        raise HTTPException(503, "Experimental depth predictions are disabled for this pilot.")
    if not ML_MODEL_PATH.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "No trained model found. Run `python -m floodsight.ml.train "
                "--synthetic` for a demo model, or train on real labeled "
                "data once available (see floodsight/ml/dataset.py)."
            ),
        )

    from floodsight.ml.predict import model_metadata, predict_depth as predict_fn

    depth = predict_fn(req.model_dump())
    meta = model_metadata()

    prov = meta.get("label_provenance") or {}
    synth_frac = prov.get("synthetic_fraction")

    if meta["metrics"].get("trained_on_synthetic_data"):
        note = (
            "Model trained on SYNTHETIC data — this number is for pipeline "
            "testing only, not a real depth estimate."
        )
    elif synth_frac and synth_frac > 0:
        note = (
            f"Model trained on mixed-provenance labels: "
            f"{prov.get('real_rows', '?')} SAR/FwDET-observed rows and "
            f"{prov.get('synthetic_rows', '?')} synthetic/pseudo-labeled rows "
            f"({synth_frac:.0%} synthetic). Treat depth as indicative, not "
            f"validated — see metrics.holdout_real_rows_only in /depth/model_info."
        )
    else:
        note = "Experimental depth estimate. Event and location validation is incomplete; do not use as an observed depth."

    _log_prediction(req, depth)

    return DepthPredictionResponse(
        predicted_depth_m=round(depth, 3),
        model_trained_on_synthetic_data=bool(meta["metrics"].get("trained_on_synthetic_data")),
        synthetic_label_fraction=synth_frac,
        note=note,
    )


@router.get("/model_info")
def model_info():
    if not ML_MODEL_PATH.exists():
        raise HTTPException(status_code=503, detail="No trained model found.")
    from floodsight.ml.predict import model_metadata

    return model_metadata()


@router.get("/predictions_log", dependencies=[Depends(require_dispatch_secret)])
def predictions_log(request: Request, limit: int = Query(100, ge=1, le=1000)):
    """
    Return the most recent prediction log entries (newest first).

    Operator-only: requires ``Authorization: Bearer <DISPATCH_SECRET>``
    (was previously public).
    """
    require_dispatch_secret(request)

    # Supabase first; JSONL fallback for local dev
    try:
        from floodsight.db.supabase_client import get_predictions

        entries = get_predictions(limit=limit)
        return {"entries": entries, "total": len(entries), "data_source": "supabase"}
    except RuntimeError:
        pass
    except Exception as exc:
        log.warning("Supabase predictions read failed (%s) — JSONL fallback", exc)

    from api.runtime import require_durable_storage
    require_durable_storage()
    if not PREDICTIONS_LOG.exists():
        return {"entries": [], "total": 0, "data_source": "local_jsonl"}
    lines = PREDICTIONS_LOG.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(ln) for ln in lines if ln.strip()]
    entries.reverse()
    return {"entries": entries[:limit], "total": len(entries), "data_source": "local_jsonl"}


# ---------------------------------------------------------------------------
# Phase 21: ML flood depth grid  (centroid-based GeoJSON)
# ---------------------------------------------------------------------------

ML_GRID_GEOJSON = DATA_DIR / "processed" / "flood_depth_ml.geojson"
ML_GRID_SUMMARY = DATA_DIR / "processed" / "flood_depth_ml_summary.json"

_VALID_CLASSES = {"None", "Low", "Medium", "High", "Extreme"}

# In-process cache — 6.5 MB file; re-reading it on every request adds
# ~1 s latency on Render free tier.  Cached once per process lifetime.
_ml_grid_cache: dict | None = None


@router.get("/ml-grid")
def ml_grid(
    depth_class: Optional[str] = Query(
        default=None,
        description=(
            "Comma-separated depth classes to return: "
            "None, Low, Medium, High, Extreme. "
            "Omit to return all cells."
        ),
    ),
    limit: int = Query(
        default=0,
        ge=0,
        description="Max features to return (0 = no limit).",
    ),
):
    """
    Experimental ML depth grid under a 150 mm rainfall scenario.
    No validated return period is assigned to this scenario.

    Returns a GeoJSON FeatureCollection of centroid points.  Each feature
    carries ``predicted_depth_m``, ``depth_class``, and ``depth_colour``
    alongside the cell's elevation, flood_score, and risk_class.

    Run ``python scripts/09_train_flood_depth.py`` once to generate the
    grid file before calling this endpoint.

    Depth classes
    -------------
    - **None**    depth < 0.05 m
    - **Low**     0.05 – 0.30 m
    - **Medium**  0.30 – 1.00 m
    - **High**    1.00 – 2.00 m
    - **Extreme** > 2.00 m
    """
    from api.runtime import experimental_depth_enabled
    if not experimental_depth_enabled():
        raise HTTPException(503, "Experimental design-storm depth layer is disabled for this pilot.")
    if not ML_GRID_GEOJSON.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "ML depth grid not yet generated. "
                "Run: python scripts/09_train_flood_depth.py"
            ),
        )

    global _ml_grid_cache
    if _ml_grid_cache is None:
        _ml_grid_cache = json.loads(ML_GRID_GEOJSON.read_text(encoding="utf-8"))
    data = _ml_grid_cache
    features = data.get("features", [])

    # Filter by depth class if requested
    if depth_class:
        requested = {c.strip() for c in depth_class.split(",")}
        unknown = requested - _VALID_CLASSES
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown depth_class value(s): {sorted(unknown)}. "
                       f"Valid: {sorted(_VALID_CLASSES)}",
            )
        features = [
            f for f in features
            if f.get("properties", {}).get("depth_class") in requested
        ]

    if limit > 0:
        features = features[:limit]

    return {
        "type":     "FeatureCollection",
        "features": features,
        "metadata": data.get("metadata", {}),
    }


@router.get("/ml-grid/summary")
def ml_grid_summary():
    """
    Return the summary statistics from the last Phase 21 training run:
    model metrics, depth class counts, top flooded cells, design storm params.
    """
    if not ML_GRID_SUMMARY.exists():
        raise HTTPException(
            status_code=503,
            detail=(
                "ML depth grid summary not found. "
                "Run: python scripts/09_train_flood_depth.py"
            ),
        )
    return json.loads(ML_GRID_SUMMARY.read_text(encoding="utf-8"))
