from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

from api.schemas import DepthPredictionRequest, DepthPredictionResponse
from floodsight.config import ML_MODEL_PATH

router = APIRouter(prefix="/depth", tags=["depth"])
log = logging.getLogger(__name__)


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
