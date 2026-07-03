"""
Africa's Talking notification sender — Phase 8.

Supports SMS (Phase 8). WhatsApp can be added in Phase 8.5 using
the same AT SDK's Airtime/Application service.

Required environment variables
--------------------------------
AT_USERNAME   Your Africa's Talking username (use 'sandbox' for testing)
AT_API_KEY    Your Africa's Talking API key
AT_SENDER_ID  Registered sender/short-code (optional; omit to use AT shared pool)
AT_RECIPIENTS Comma-separated E.164 phone numbers: +2348012345678,+2349012345678

Install dependency:
    pip install africastalking
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger(__name__)


def send_sms(
    message: str,
    recipients: list[str],
    dry_run: bool = False,
) -> dict:
    """
    Send an SMS to one or more phone numbers via Africa's Talking.

    Parameters
    ----------
    message    : SMS body (keep ≤ 160 chars to stay in a single SMS segment).
    recipients : List of E.164 numbers, e.g. ["+2348012345678"].
    dry_run    : If True, prints the message and returns without calling AT.

    Returns the AT SDK response dict on success.
    Raises ValueError if env vars are missing.
    Raises RuntimeError if the AT API call fails.
    """
    username  = os.environ.get("AT_USERNAME", "").strip()
    api_key   = os.environ.get("AT_API_KEY",  "").strip()
    sender_id = os.environ.get("AT_SENDER_ID", "").strip() or None

    if not username:
        raise ValueError("AT_USERNAME environment variable is not set.")
    if not api_key:
        raise ValueError("AT_API_KEY environment variable is not set.")
    if not recipients:
        raise ValueError("No recipients provided.")

    if dry_run:
        log.info("[DRY RUN] Would send to %s:", recipients)
        log.info("[DRY RUN] Message (%d chars): %s", len(message), message)
        return {"status": "dry_run", "recipients": recipients, "message": message}

    try:
        import africastalking  # pip install africastalking
    except ImportError as exc:
        raise RuntimeError(
            "africastalking package is not installed. "
            "Run: pip install africastalking"
        ) from exc

    africastalking.initialize(username, api_key)
    sms = africastalking.SMS

    try:
        response = sms.send(message, recipients, sender_id=sender_id)
        log.info("AT SMS sent. Response: %s", response)
        return response
    except Exception as exc:
        raise RuntimeError(f"Africa's Talking API error: {exc}") from exc
