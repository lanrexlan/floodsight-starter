"""
POST /verify  — field verification intake for Phase 6 recalibration.

Field partners submit one verification per flooded (or not-flooded) location
after each event. These records are matched against the dispatch cell
snapshot (what the system actually warned) and used to compute
false-positive / false-negative rates, which drive both ML retraining and
susceptibility weight recalibration.

Security
--------
POST /verify requires ``Authorization: Bearer <VERIFY_SECRET>`` (falls back
to DISPATCH_SECRET when VERIFY_SECRET is unset). Without auth, anyone on
the internet could poison the ground-truth data that recalibrates the
model. GET /verify/summary returns only aggregate counts publicly;
individual entries (which contain reporter names — PII) require the
operator secret.

Storage
-------
Verifications persist in Supabase (scripts/sql/03_logs.sql). The local
JSONL file is only a fallback for development without Supabase — on Render
the local disk is EPHEMERAL and wiped every deploy.

Workflow:
  1. FloodSight issues a warning for cell X (dispatch snapshots the cell).
  2. A community reporter visits cell X after the event.
  3. Reporter (via the partner app holding VERIFY_SECRET) calls POST /verify
     with lat, lon, event_date, observed_flooded, optionally observed_depth_m.
  4. scripts/recalibrate.py compares verifications against dispatch_cells
     to retrain the model and flag systematically wrong cells.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Depends

from api.auth import has_dispatch_secret, require_verify_secret
from api.schemas import VerifyRequest, VerifyResponse
from floodsight.config import DATA_DIR

router = APIRouter(prefix="/verify", tags=["verification"])
log = logging.getLogger(__name__)

LOGS_DIR = DATA_DIR / "logs"
VERIFICATIONS_LOG = LOGS_DIR / "verifications.jsonl"


def _load_entries() -> tuple[list[dict], str]:
    """All verification entries — Supabase first, JSONL fallback."""
    try:
        from floodsight.db.supabase_client import get_verifications

        return get_verifications(), "supabase"
    except RuntimeError:
        pass
    except Exception as exc:
        log.warning("Supabase verifications read failed (%s) — JSONL fallback", exc)

    from api.runtime import require_durable_storage
    require_durable_storage()
    if not VERIFICATIONS_LOG.exists():
        return [], "local_jsonl"
    lines = VERIFICATIONS_LOG.read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines if ln.strip()], "local_jsonl"


def store_verification(
    lat: float,
    lon: float,
    event_date: str,
    observed_flooded: bool,
    observed_depth_m: float | None = None,
    reporter: str | None = None,
    notes: str | None = None,
) -> dict:
    """
    Persist one verification entry (Supabase first, JSONL fallback).

    Shared by POST /verify and the inbound SMS webhook (/at/incoming),
    so both channels produce identical records for recalibration.
    Returns the stored entry (including its verification_id).
    """
    vid = str(uuid.uuid4())[:8]
    entry = {
        "verification_id": vid,
        "ts": datetime.now(timezone.utc).isoformat(),
        "lat": lat,
        "lon": lon,
        "event_date": event_date,
        "observed_flooded": observed_flooded,
        "observed_depth_m": observed_depth_m,
        "reporter": reporter,
        "notes": notes,
    }

    stored = False
    try:
        from floodsight.db.supabase_client import add_verification

        add_verification(entry)
        stored = True
    except RuntimeError:
        pass  # Supabase not configured — JSONL fallback
    except Exception as exc:
        log.error("Supabase verification insert failed (%s) — JSONL fallback", exc)

    if not stored:
        from api.runtime import require_durable_storage
        require_durable_storage()
        LOGS_DIR.mkdir(parents=True, exist_ok=True)
        with open(VERIFICATIONS_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")

    log.info(
        "Verification %s logged: flooded=%s at (%.4f, %.4f)",
        vid, observed_flooded, lat, lon,
    )
    return entry


@router.post("", response_model=VerifyResponse, dependencies=[Depends(require_verify_secret)])
def submit_verification(req: VerifyRequest, request: Request):
    """Record a field verification report for a location after a flood event."""
    require_verify_secret(request)

    entry = store_verification(
        lat=req.lat,
        lon=req.lon,
        event_date=req.event_date.isoformat(),
        observed_flooded=req.observed_flooded,
        observed_depth_m=req.observed_depth_m,
        reporter=req.reporter,
        notes=req.notes,
    )
    return VerifyResponse(
        status="ok",
        message=f"Verification recorded. ID: {entry['verification_id']}",
        verification_id=entry["verification_id"],
    )


@router.get("/summary")
def verification_summary(request: Request):
    """
    Aggregate verification counts (public).

    Individual entries contain reporter names/notes (PII) and are only
    included when the caller presents the operator bearer secret.
    """
    entries, source = _load_entries()
    flooded = sum(1 for e in entries if e.get("observed_flooded"))

    out = {
        "total": len(entries),
        "flooded": flooded,
        "not_flooded": len(entries) - flooded,
        "data_source": source,
    }
    if has_dispatch_secret(request):
        out["entries"] = sorted(entries, key=lambda e: e.get("ts", ""), reverse=True)
    return out
