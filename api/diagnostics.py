"""
Configuration diagnostics.

Why this exists
---------------
FloodSight degrades silently when an environment variable is missing. Several
subsystems fail *closed* by design — the right behaviour for a life-safety
system — but a closed failure with no operator-visible signal is
indistinguishable from "nothing happened today":

  * AT_WEBHOOK_TOKEN unset  -> POST /at/incoming returns 503 for every
    callback. Residents replying STOP are never unsubscribed (an NDPR opt-out
    obligation) and CHEW replies (CONFIRM / REPORT n) are never logged, which
    silently destroys the pilot's primary intermediary outcome data.
  * AT_USERNAME / AT_API_KEY unset -> every SMS raises at send time.
  * SUPABASE_URL / SUPABASE_KEY unset -> subscriber writes 503, and several
    dashboard endpoints quietly fall back to synthetic demo data.

Each of those was invisible until someone went looking. This module turns the
implicit state into an explicit report, logged once at startup and exposed at
GET /diagnostics for the operator dashboard.

Security note: this endpoint never returns secret VALUES, only whether each
name is set, so it is safe to leave unauthenticated alongside the other public
status routes.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ConfigItem:
    name:     str
    required: bool
    impact:   str   # what breaks, in operator language, when this is missing


# Ordered roughly by blast radius.
CONFIG_ITEMS: tuple[ConfigItem, ...] = (
    ConfigItem(
        "SUPABASE_URL", True,
        "Subscriber sign-up, alert logging and all dashboard counts fail; "
        "endpoints fall back to synthetic demo data.",
    ),
    ConfigItem(
        "SUPABASE_KEY", True,
        "Same as SUPABASE_URL — no subscriber or alert data can be read or written.",
    ),
    ConfigItem(
        "AT_USERNAME", True,
        "No SMS of any kind can be sent (resident alerts, CHEW health alerts, "
        "welcome messages).",
    ),
    ConfigItem(
        "AT_API_KEY", True,
        "No SMS of any kind can be sent.",
    ),
    ConfigItem(
        "AT_WEBHOOK_TOKEN", True,
        "POST /at/incoming returns 503 for every Africa's Talking callback: "
        "STOP replies are not honoured (NDPR opt-out failure) and CHEW "
        "CONFIRM/REPORT replies are not recorded (loses PoC outcome data).",
    ),
    ConfigItem(
        "DISPATCH_SECRET", True,
        "Operator-only endpoints (/alerts/dispatch, unsubscribe) cannot be "
        "authenticated, so the scheduled dispatch workflow cannot run.",
    ),
    ConfigItem(
        "AT_SENDER_ID", False,
        "Messages send from the Africa's Talking shared pool instead of the "
        "registered FloodSight sender ID.",
    ),
    ConfigItem(
        "FLOODSIGHT_API", False,
        "Scheduled scripts fall back to the default public base URL.",
    ),
    ConfigItem(
        "REQUIRE_OTP", False,
        "OTP confirmation on /subscribe stays disabled (default).",
    ),
)


def _is_set(name: str) -> bool:
    return bool(os.getenv(name, "").strip())


def config_report() -> dict:
    """
    Build the configuration report.

    Returns a dict with an overall ``status`` of "ok" | "degraded", plus the
    per-variable detail. ``degraded`` means at least one REQUIRED variable is
    unset and some user-facing capability is therefore switched off.
    """
    missing_required: list[dict] = []
    missing_optional: list[dict] = []

    for item in CONFIG_ITEMS:
        if _is_set(item.name):
            continue
        entry = {"name": item.name, "impact": item.impact}
        (missing_required if item.required else missing_optional).append(entry)

    return {
        "status":           "degraded" if missing_required else "ok",
        "checked":          len(CONFIG_ITEMS),
        "missing_required": missing_required,
        "missing_optional": missing_optional,
        "configured": sorted(i.name for i in CONFIG_ITEMS if _is_set(i.name)),
    }


def log_config_report() -> dict:
    """
    Emit the report to the application log at startup.

    Missing REQUIRED variables are logged at ERROR so they surface in Render's
    log view without anyone having to query an endpoint — the whole point is
    that these failures should stop being silent.
    """
    report = config_report()

    for entry in report["missing_required"]:
        log.error(
            "CONFIG MISSING (required): %s — %s", entry["name"], entry["impact"]
        )
    for entry in report["missing_optional"]:
        log.warning(
            "CONFIG MISSING (optional): %s — %s", entry["name"], entry["impact"]
        )

    if report["status"] == "ok":
        log.info(
            "Configuration OK — all %d required variables set.", report["checked"]
        )
    else:
        log.error(
            "Configuration DEGRADED — %d required variable(s) unset. "
            "See GET /diagnostics.",
            len(report["missing_required"]),
        )

    return report
