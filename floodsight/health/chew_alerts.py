"""
FloodSight Health Intelligence Layer — CHEW Alert Dispatch.

Composes and sends SMS alerts to Community Health Extension Workers (CHEWs)
in the five pilot LGAs when the outbreak probability engine scores Moderate
or above.

Message design principles
--------------------------
- Literacy level: secondary school (plain English, no jargon)
- Length: strictly <= 160 characters (single SMS unit — highest delivery rate)
- Action clarity: one concrete action per message
- Reply instructions: CONFIRM or REPORT N cases

Template was tested with 10 CHEWs in a pre-pilot comprehension exercise
(Month 2 deliverable). Re-test if template changes.
"""

from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime

from floodsight.config import HEALTH_PILOT_LGAS

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Message composition
# ---------------------------------------------------------------------------

_TIER_ACTIONS: dict[str, str] = {
    "Moderate": "Check malaria RDT stock. Watch for fever cases.",
    "High":     "Pre-position RDT kits and bed nets NOW. Cases expected.",
    "Critical": "URGENT: Distribute nets+RDTs. Begin community sensitization.",
}


def compose_message(
    lga_name: str,
    risk_tier: str,
    outbreak_window_start: str,
    outbreak_window_end: str,
    inundation_km2: float,
) -> str:
    """
    Build a <=160-character SMS alert for a CHEW.

    Raises ValueError if risk_tier is 'Low' (callers should filter before
    calling this function).
    """
    if risk_tier == "Low":
        raise ValueError("Low-tier LGAs do not receive CHEW alerts")

    w_start = datetime.fromisoformat(outbreak_window_start).strftime("%d %b").lstrip("0")
    w_end   = datetime.fromisoformat(outbreak_window_end).strftime("%d %b").lstrip("0")
    action  = _TIER_ACTIONS.get(risk_tier, "Monitor closely for fever cases.")

    msg = (
        f"FloodSight Health [{lga_name}]: "
        f"Flood water ({inundation_km2:.1f}km2) may raise malaria risk "
        f"{w_start}-{w_end}. "
        f"{action} Reply CONFIRM."
    )

    # Hard trim — should never trigger with current template
    if len(msg) > 160:
        msg = msg[:157] + "..."

    return msg


# ---------------------------------------------------------------------------
# Idempotency key
# ---------------------------------------------------------------------------

def _idem_key(lga_name: str, phone: str, today_str: str) -> str:
    """SHA-256 idempotency key (first 32 hex chars) for one CHEW-day-LGA triple."""
    raw = f"{lga_name}:{phone}:{today_str}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------

def dispatch_health_alerts(
    scored_lgas: list[dict],
    risk_ids: dict[str, int],
) -> dict:
    """
    Send SMS alerts to CHEWs in pilot LGAs where risk_tier >= Moderate.

    Parameters
    ----------
    scored_lgas : list of dicts from engine.score_lgas()
    risk_ids    : mapping of lga_name -> lga_health_risk.id (from DB insert)

    Returns
    -------
    dict with summary counts:
        sent, skipped_already_sent, skipped_low_risk,
        skipped_not_pilot, failed
    """
    import os
    if os.getenv("FLOODSIGHT_ENV") == "production" and os.getenv("HEALTH_DISPATCH_ENABLED", "false").lower() != "true":
        raise RuntimeError("Health SMS dispatch requires approval of the research pilot and HEALTH_DISPATCH_ENABLED=true.")
    from floodsight.db.supabase_client import (
        alert_already_sent_today,
        get_chew_subscribers_for_lga,
        log_health_alert,
    )
    from floodsight.notifications.africastalking import send_sms as _at_send

    summary = {
        "sent":                  0,
        "skipped_already_sent":  0,
        "skipped_low_risk":      0,
        "skipped_not_pilot":     0,
        "failed":                0,
    }

    today_str = date.today().isoformat()

    for lga in scored_lgas:
        lga_name  = lga["lga_name"]
        risk_tier = lga["risk_tier"]

        if lga_name not in HEALTH_PILOT_LGAS:
            summary["skipped_not_pilot"] += 1
            continue

        if risk_tier == "Low":
            summary["skipped_low_risk"] += 1
            continue

        risk_id     = risk_ids.get(lga_name)
        subscribers = get_chew_subscribers_for_lga(lga_name)

        if not subscribers:
            log.warning("No active CHEWs for %s — skipping", lga_name)
            continue

        try:
            message = compose_message(
                lga_name=lga_name,
                risk_tier=risk_tier,
                outbreak_window_start=lga["outbreak_window_start"],
                outbreak_window_end=lga["outbreak_window_end"],
                inundation_km2=lga["inundation_area_km2"],
            )
        except ValueError:
            summary["skipped_low_risk"] += 1
            continue

        for chew in subscribers:
            phone    = chew["phone"]
            idem_key = _idem_key(lga_name, phone, today_str)

            if alert_already_sent_today(idem_key):
                summary["skipped_already_sent"] += 1
                continue

            try:
                result     = _at_send(message=message, recipients=[phone])
                # AT SDK response: {"SMSMessageData": {"Recipients": [{...}]}}
                recipient  = (result.get("SMSMessageData", {}).get("Recipients") or [{}])[0]
                at_msg_id  = recipient.get("messageId")
                at_status  = recipient.get("status", "Unknown")
                at_cost    = recipient.get("cost")

                log_health_alert(
                    chew_id=chew["id"],
                    risk_id=risk_id,
                    lga_name=lga_name,
                    phone=phone,
                    message_text=message,
                    at_message_id=at_msg_id,
                    at_status=at_status,
                    at_cost=at_cost,
                    idempotency_key=idem_key,
                )
                summary["sent"] += 1
                log.info(
                    "Health alert sent → %s (%s tier, %s)",
                    phone, risk_tier, lga_name,
                )

            except Exception as exc:
                log.error("Failed to send health alert to %s: %s", phone, exc)
                summary["failed"] += 1

    return summary
