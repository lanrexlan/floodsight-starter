"""
SMS alert sender for FloodSight — Africa's Talking.

Africa's Talking has direct connections to MTN, Airtel, Glo, and 9mobile
and is ~10× cheaper than Twilio for Nigerian SMS delivery.

Environment variables required (set in Render dashboard):
    AT_USERNAME   — your Africa's Talking username (use 'sandbox' for testing)
    AT_API_KEY    — your Africa's Talking API key
    AT_SENDER_ID  — registered sender ID or short-code (optional; omit to use
                    the AT shared pool, e.g. "FloodSight")

If any required env var is missing, send_sms() raises RuntimeError.
All other exceptions (AT API errors) are propagated so dispatch.py can log
them and count failed sends.

Message guidelines
------------------
- Keep under 160 characters to avoid split-billing (GSM-7 encoding).
- Include area name so recipients know the message is relevant to them.
- Always include a STOP opt-out instruction.
- Use a clear, calm tone — panic phrasing is counterproductive.
"""

from __future__ import annotations

import logging

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
# Africa's Talking sender
# ---------------------------------------------------------------------------

def send_sms(to_number: str, alert_level: str, area_name: str | None = None) -> None:
    """
    Send a flood alert SMS via Africa's Talking.

    Parameters
    ----------
    to_number   : E.164 recipient number, e.g. +2348012345678
    alert_level : "Watch" or "Warning"
    area_name   : human-readable location name (optional but recommended)

    Raises
    ------
    RuntimeError : missing environment variables or AT API error
    """
    from floodsight.notifications.africastalking import send_sms as _at_send

    body = _build_message(alert_level, area_name)
    log.debug("SMS → %s | %s | %d chars", to_number, alert_level, len(body))

    _at_send(message=body, recipients=[to_number])

    log.info(
        "SMS sent via AT to=%s level=%s area=%s",
        to_number, alert_level, area_name,
    )
