from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, HTTPException

from api.schemas import DepthPredictionRequest, DepthPredictionResponse
from floodsight.config import DATA_DIR, ML_MODEL_PATH

router = APIRouter(prefix="/depth", tags=["depth"])
log = logging.getLogger(__name__)

LOGS_DIR = DATA_DIR / "logs"
PREDICTIONS_LOG = LOGS_DIR / "predictions.jsonl"


def _log_prediction(req: DepthPredictionRequest, predicted_depth_m: float) -> None:
    """Append one prediction to the JSONL log (fire-and-forget, non-fatal)."""
    try:
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
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
        with open(PREDICTIONS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as exc:  # never crash the API over logging
        log.warning("Failed to write prediction log: %s", exc)


@router.post("/predict", response_model=DepthPredictionResponse)
def predict_depth(req: DepthPredictionRequest):
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
    note = (
        "Model trained on SYNTHETIC data — this number is for pipeline "
        "testing only, not a real depth estimate."
        if meta["metrics"].get("trained_on_synthetic_data")
        else None
    )

    _log_prediction(req, depth)

    return DepthPredictionResponse(
        predicted_depth_m=round(depth, 3),
        model_trained_on_synthetic_data=bool(meta["metrics"].get("trained_on_synthetic_data")),
        note=note,
    )


@router.get("/model_info")
def model_info():
    if not ML_MODEL_PATH.exists():
        raise HTTPException(status_code=503, detail="No trained model found.")
    from floodsight.ml.predict import model_metadata

    return model_metadata()


@router.get("/predictions_log")
def predictions_log(limit: int = 100):
    """Return the most recent prediction log entries (newest first)."""
    if not PREDICTIONS_LOG.exists():
        return {"entries": [], "total": 0}
    lines = PREDICTIONS_LOG.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(ln) for ln in lines if ln.strip()]
    entries.reverse()
    return {"entries": entries[:limit], "total": len(entries)}
