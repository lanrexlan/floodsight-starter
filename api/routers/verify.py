"""
POST /verify  — field verification intake for Phase 6 recalibration.

Field partners submit one verification per flooded (or not-flooded) location
after each event. These records are matched against prediction logs and used
to compute false-positive / false-negative rates, which drive both ML
retraining and susceptibility weight recalibration.

Workflow:
  1. FloodSight issues a warning for cell X.
  2. A community reporter visits cell X after the event.
  3. Reporter calls POST /verify with lat, lon, event_date, observed_flooded,
     and optionally observed_depth_m.
  4. scripts/recalibrate.py reads verifications.jsonl alongside
     data/processed/real_training_dataset.csv to retrain the model and
     flag systematically wrong cells.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter

from api.schemas import VerifyRequest, VerifyResponse
from floodsight.config import DATA_DIR

router = APIRouter(prefix="/verify", tags=["verification"])
log = logging.getLogger(__name__)

LOGS_DIR = DATA_DIR / "logs"
VERIFICATIONS_LOG = LOGS_DIR / "verifications.jsonl"


@router.post("", response_model=VerifyResponse)
def submit_verification(req: VerifyRequest):
    """Record a field verification report for a location after a flood event."""
    LOGS_DIR.mkdir(parents=True, exist_ok=True)
    vid = str(uuid.uuid4())[:8]
    entry = {
        "verification_id": vid,
        "ts": datetime.now(timezone.utc).isoformat(),
        "lat": req.lat,
        "lon": req.lon,
        "event_date": req.event_date,
        "observed_flooded": req.observed_flooded,
        "observed_depth_m": req.observed_depth_m,
        "reporter": req.reporter,
        "notes": req.notes,
    }
    with open(VERIFICATIONS_LOG, "a", encoding="utf-8") as f:
        f.write(json.dumps(entry) + "\n")
    log.info("Verification %s logged: flooded=%s at (%.4f, %.4f)", vid, req.observed_flooded, req.lat, req.lon)
    return VerifyResponse(
        status="ok",
        message=f"Verification recorded. ID: {vid}",
        verification_id=vid,
    )


@router.get("/summary")
def verification_summary():
    """Return all filed verifications with aggregate counts."""
    if not VERIFICATIONS_LOG.exists():
        return {"total": 0, "flooded": 0, "not_flooded": 0, "entries": []}
    lines = VERIFICATIONS_LOG.read_text(encoding="utf-8").splitlines()
    entries = [json.loads(ln) for ln in lines if ln.strip()]
    flooded = sum(1 for e in entries if e.get("observed_flooded"))
    return {
        "total": len(entries),
        "flooded": flooded,
        "not_flooded": len(entries) - flooded,
        "entries": sorted(entries, key=lambda e: e["ts"], reverse=True),
    }
