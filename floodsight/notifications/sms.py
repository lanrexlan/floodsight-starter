"""
SMS alert sender for FloodSight Phase 16 — Twilio.

Environment variables required (set in Render dashboard):
    TWILIO_ACCOUNT_SID   — from Twilio console (starts with AC…)
    TWILIO_AUTH_TOKEN    — from Twilio console
    TWILIO_FROM_NUMBER   — your Twilio phone number in E.164, e.g. +12345678901

If any env var is missing, send_sms() raises RuntimeError.
All other exceptions (Twilio API errors) are propagated so the caller
(dispatch.py) can log them and count failed sends.

Message guidelines
------------------
- Keep under 160 characters to avoid split-billing.
- Include area name so recipients know the message is relevant to them.
- Always include reply STOP opt-out (Twilio handles this automatically
  for US numbers; for Nigerian numbers it's good practice regardless).
- Use a clear, calm tone — panic phrasing is counterproductive.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)

# Max SMS length before split-billing kicks in (GSM-7 encoding)
_MAX_CHARS = 160

# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

def _build_message(alert_level: str, area_name: str | None) -> str:
    area = area_name or "your area"

    if alert_level == "Warning":
        msg = (
            f"FloodSight Lagos ALERT: Flood Warning issued for {area}. "
            "Avoid low-lying roads. Seek higher ground if needed. "
            "Details: rankineinnovationlab.com/floodsight | Reply STOP to opt out"
        )
    else:  # Watch
        msg = (
            f"FloodSight Lagos: Flood Watch for {area}. "
            "Heavy rain expected — avoid flood-prone streets. "
            "Track live: rankineinnovationlab.com/floodsight | Reply STOP to opt out"
        )

    # Trim to 160 chars without cutting mid-word
    if len(msg) > _MAX_CHARS:
        msg = msg[:_MAX_CHARS - 1].rsplit(" ", 1)[0] + "…"

    return msg


# ---------------------------------------------------------------------------
# Twilio sender
# ---------------------------------------------------------------------------

def send_sms(to_number: str, alert_level: str, area_name: str | None = None) -> str:
    """
    Send a flood alert SMS via Twilio.

    Parameters
    ----------
    to_number   : E.164 recipient number, e.g. +2348012345678
    alert_level : "Watch" or "Warning"
    area_name   : human-readable location name (optional but recommended)

    Returns
    -------
    str : Twilio message SID (e.g. "SM…") — useful for logging.

    Raises
    ------
    RuntimeError : missing environment variables
    TwilioRestException : API error from Twilio (network, invalid number, etc.)
    """
    sid   = os.getenv("TWILIO_ACCOUNT_SID",  "").strip()
    token = os.getenv("TWILIO_AUTH_TOKEN",   "").strip()
    from_ = os.getenv("TWILIO_FROM_NUMBER",  "").strip()

    if not sid or not token or not from_:
        raise RuntimeError(
            "TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, and TWILIO_FROM_NUMBER "
            "must be set as environment variables."
        )

    from twilio.rest import Client as TwilioClient  # lazy import

    body = _build_message(alert_level, area_name)
    log.debug("SMS → %s | %s | %d chars", to_number, alert_level, len(body))

    client  = TwilioClient(sid, token)
    message = client.messages.create(body=body, from_=from_, to=to_number)

    log.info(
        "SMS sent SID=%s to=%s level=%s area=%s",
        message.sid, to_number, alert_level, area_name,
    )
    return message.sid
