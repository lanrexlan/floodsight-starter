"""
POST /at/incoming — Africa's Talking inbound SMS webhook.

Closes two P2 gaps in one endpoint:

  * STOP handling actually exists now (the outbound templates have promised
    "Reply STOP to opt out" since Phase 16, but nothing was listening).
  * Field verification by SMS: partners and residents can report ground
    truth by texting instead of calling POST /verify with a bearer token.

Supported keywords (case-insensitive, leading/trailing noise tolerated):

    STOP | END | QUIT | UNSUBSCRIBE   -> deactivate subscriber
    START | RESUME | SUBSCRIBE        -> reactivate subscriber
    FLOOD [depth]                     -> verification: flooded at their
                                         registered location. Depth optional:
                                         "FLOOD 0.5" (metres) or "FLOOD 50CM".
    NOFLOOD | NO FLOOD | DRY          -> verification: not flooded.

Verification reports are keyed to the sender's registered subscriber
location (lat/lon) with event_date = today (Lagos). Unknown senders can
still STOP (no-op) but cannot file verifications — location unknown.

Setup
-----
1. Set AT_WEBHOOK_TOKEN in Render (any random string).
2. Africa's Talking dashboard -> SMS -> Callbacks -> Incoming messages:
       https://<your-app>.onrender.com/at/incoming?token=<AT_WEBHOOK_TOKEN>
   AT posts application/x-www-form-urlencoded with fields:
   from, to, text, date, id, linkId.

AT does not sign callbacks, so the token query parameter is the auth.
"""

from __future__ import annotations

import hmac
import logging
import os
import re

from fastapi import APIRouter, Form, HTTPException, Query

log = logging.getLogger(__name__)

router = APIRouter(tags=["inbound"])

_STOP_WORDS  = {"STOP", "END", "QUIT", "UNSUBSCRIBE", "CANCEL", "OPTOUT", "OPT-OUT"}
_START_WORDS = {"START", "RESUME", "SUBSCRIBE", "UNSTOP"}
_DRY_WORDS   = {"NOFLOOD", "NO FLOOD", "DRY", "NOT FLOODED", "NO"}


def parse_inbound(text: str) -> tuple[str, float | None]:
    """
    Classify an inbound SMS body.

    Returns (kind, depth_m) where kind is one of:
    'stop', 'start', 'flood', 'dry', 'unknown'.
    depth_m is only non-None for 'flood' with a parseable depth.
    """
    t = (text or "").strip().upper()
    t = re.sub(r"[.!,;:]+$", "", t).strip()

    if t in _STOP_WORDS:
        return "stop", None
    if t in _START_WORDS:
        return "start", None
    if t in _DRY_WORDS:
        return "dry", None

    m = re.match(r"^FLOOD(?:ED)?\b\s*(.*)$", t)
    if m:
        rest = m.group(1).strip()
        if not rest:
            return "flood", None
        # "0.5", "0.5M", "50CM"
        dm = re.match(r"^(\d+(?:\.\d+)?)\s*(M|CM)?$", rest)
        if dm:
            val = float(dm.group(1))
            unit = dm.group(2) or "M"
            depth = val / 100.0 if unit == "CM" else val
            # sanity clamp: people don't stand in 10m of water to text
            if 0 <= depth <= 5.0:
                return "flood", round(depth, 3)
        return "flood", None

    return "unknown", None


def _check_token(token: str) -> None:
    expected = os.getenv("AT_WEBHOOK_TOKEN", "").strip()
    if not expected:
        raise HTTPException(status_code=503, detail="AT_WEBHOOK_TOKEN not set.")
    if not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail="Unauthorized.")


@router.post("/at/incoming")
def at_incoming(
    token: str = Query(""),
    from_: str = Form("", alias="from"),
    text: str = Form(""),
    date: str = Form(""),
    id: str = Form(""),
):
    """Handle one inbound SMS from Africa's Talking."""
    _check_token(token)

    from floodsight.db.supabase_client import (
        deactivate_subscriber,
        get_subscriber_by_phone,
        normalize_phone,
        reactivate_subscriber,
        today_lagos,
    )

    try:
        phone = normalize_phone(from_)
    except ValueError:
        log.warning("Inbound SMS from unparseable number %r — ignored", from_)
        return {"status": "ignored", "reason": "bad_number"}

    kind, depth_m = parse_inbound(text)
    log.info("Inbound SMS %s from %s -> %s (depth=%s)", id, phone, kind, depth_m)

    try:
        if kind == "stop":
            found = deactivate_subscriber(phone)
            return {"status": "unsubscribed" if found else "not_found", "action": "stop"}

        if kind == "start":
            found = reactivate_subscriber(phone)
            return {"status": "resubscribed" if found else "not_found", "action": "start"}

        if kind in ("flood", "dry"):
            sub = get_subscriber_by_phone(phone)
            if not sub:
                return {"status": "ignored", "reason": "unknown_sender"}
            from api.routers.verify import store_verification

            entry = store_verification(
                lat=sub["lat"],
                lon=sub["lon"],
                event_date=today_lagos(),
                observed_flooded=(kind == "flood"),
                observed_depth_m=depth_m,
                reporter=f"sms:{phone}",
                notes=f"Inbound SMS report: {text!r}",
            )
            return {
                "status": "verification_recorded",
                "verification_id": entry["verification_id"],
                "observed_flooded": kind == "flood",
            }

    except RuntimeError as exc:
        # Supabase not configured
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    return {"status": "ignored", "reason": "unrecognised_keyword"}
