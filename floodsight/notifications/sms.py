"""
SMS alert sender for FloodSight — Africa's Talking.

Africa's Talking has direct connections to MTN, Airtel, Glo, and 9mobile
and is ~10x cheaper than Twilio for Nigerian SMS delivery.

Environment variables required (set in Render dashboard):
    AT_USERNAME   — your Africa's Talking username (use 'sandbox' for testing)
    AT_API_KEY    — your Africa's Talking API key
    AT_SENDER_ID  — registered sender ID or short-code (optional; omit to use
                    the AT shared pool, e.g. "FloodSight")

If any required env var is missing, send_sms() raises RuntimeError.
All other exceptions (AT API errors) are propagated so dispatch.py can log
them and count failed sends.

Message guidelines (enforced by _build_message, tested in tests/)
------------------------------------------------------------------
- <=160 chars in GSM-7 so every alert bills as ONE segment. The previous
  template was 178 chars with a typical area name; the trim cut the
  "Reply STOP" opt-out (an NDPR compliance problem) and appended a U+2026
  ellipsis — a non-GSM-7 character that silently switched the whole
  message to UCS-2 encoding, splitting it into 3 billed segments.
- The opt-out instruction is composed LAST and is never truncated;
  the details section shrinks instead.
- GSM-7-safe characters only (no em dashes, no Unicode ellipsis).
- Include the area name so recipients know the message is relevant.
- Clear, calm tone — panic phrasing is counterproductive.
"""

from __future__ import annotations

import logging

log = logging.getLogger(__name__)

# Max SMS length for a single segment (GSM-7 encoding)
_MAX_CHARS = 160

# Opt-out suffix — REQUIRED on every message, never truncated.
_STOP_SUFFIX = " Reply STOP to opt out"

# Basic GSM-7 alphabet (plus extension chars we allow). Anything outside
# this set forces UCS-2 encoding for the WHOLE message -> 70-char segments.
_GSM7 = set(
    "@£$¥èéùìòÇ\nØø\rÅå"
    "Δ_ΦΓΛΩΠΨΣΘΞ"
    "ÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
    "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§"
    "¿abcdefghijklmnopqrstuvwxyzäöñüà"
    "^{}\\[~]|€"
)


def is_gsm7(text: str) -> bool:
    """True if every character fits the GSM-7 alphabet (single-segment safe)."""
    return all(ch in _GSM7 for ch in text)


# ---------------------------------------------------------------------------
# Message templates
# ---------------------------------------------------------------------------

def _build_message(alert_level: str, area_name: str | None) -> str:
    """
    Compose an alert SMS that is guaranteed to:
      1. end with the STOP opt-out instruction (never truncated),
      2. fit in one GSM-7 segment (<=160 chars),
      3. contain only GSM-7 characters.

    If the message would exceed 160 chars, the safety advice is kept and
    the map URL dropped first; pathological area names are word-trimmed.
    The opt-out suffix always stays.
    """
    area = (area_name or "your area").strip()

    if alert_level == "Warning":
        head   = f"FloodSight ALERT: Flood Warning for {area}."
        detail = " Avoid low roads. Move to higher ground if needed."
    elif alert_level == "All Clear":
        head   = f"FloodSight: All clear for {area}."
        detail = " Flood alert has ended. Stay careful near drains and canals."
    else:  # Watch
        head   = f"FloodSight: Flood Watch for {area}."
        detail = " Heavy rain expected - avoid flood-prone streets."

    url = " Map: rankineinnovationlab.com/floodsight"

    budget = _MAX_CHARS - len(_STOP_SUFFIX)

    # Add optional parts only while they fit: safety advice first, URL last.
    msg = head
    if len(msg + detail) <= budget:
        msg += detail
    if len(msg + url) <= budget:
        msg += url
    if len(msg) > budget:
        # Extreme area names: hard-trim at a word boundary
        msg = msg[:budget].rsplit(" ", 1)[0]

    msg = msg + _STOP_SUFFIX

    # Belt and braces — a non-GSM-7 char would triple the billing
    if not is_gsm7(msg):
        msg = "".join(ch if ch in _GSM7 else "?" for ch in msg)
        log.warning("Non-GSM-7 characters replaced in SMS body: %r", msg)

    return msg


# ---------------------------------------------------------------------------
# Africa's Talking sender
# ---------------------------------------------------------------------------

def send_otp(to_number: str, code: str) -> None:
    """
    Send a subscription confirmation code (REQUIRE_OTP flow).

    Kept intentionally terse: single GSM-7 segment, no links (links in an
    unexpected first-contact SMS look like phishing).
    """
    from floodsight.notifications.africastalking import send_sms as _at_send

    body = (
        f"FloodSight code: {code}. "
        "Enter it to confirm your flood alert subscription. "
        "Not you? Ignore this message."
    )
    _at_send(message=body, recipients=[to_number])
    log.info("OTP sent to %s", to_number)


def send_sms(
    to_number: str, alert_level: str, area_name: str | None = None
) -> dict:
    """
    Send a flood alert SMS via Africa's Talking.

    Parameters
    ----------
    to_number   : E.164 recipient number, e.g. +2348012345678
    alert_level : "Watch", "Warning", or "All Clear"
    area_name   : human-readable location name (optional but recommended)

    Returns
    -------
    dict
        The recipient record from the Africa's Talking response::

            {"statusCode": 101, "number": "+234...", "status": "Success",
             "cost": "NGN 2.2000", "messageId": "ATXid_..."}

        Returns ``{}`` if AT returns no recipient entry.

        This previously returned None, which meant the ``messageId`` was
        discarded at the call site. Without it there is no correlation key to
        match an inbound Africa's Talking delivery report back to the
        alert_log row, so delivery could never be confirmed — the dashboard
        could only ever report "submitted to gateway" as though it were
        "received by resident".

    Raises
    ------
    RuntimeError : missing environment variables or AT API error
    """
    from floodsight.notifications.africastalking import send_sms as _at_send

    body = _build_message(alert_level, area_name)
    log.debug("SMS -> %s | %s | %d chars", to_number, alert_level, len(body))

    result = _at_send(message=body, recipients=[to_number])

    # AT response shape: {"SMSMessageData": {"Recipients": [{...}]}}
    recipient = (
        (result or {}).get("SMSMessageData", {}).get("Recipients") or [{}]
    )[0]

    log.info(
        "SMS sent via AT to=%s level=%s area=%s status=%s id=%s",
        to_number, alert_level, area_name,
        recipient.get("status"), recipient.get("messageId"),
    )
    return recipient
