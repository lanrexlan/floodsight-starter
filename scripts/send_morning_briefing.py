"""
FloodSight morning briefing SMS sender — Phase 8.

Fetches today's forecast summary from the live API, formats a brief SMS,
and sends it to all registered recipients via Africa's Talking.

Usage (from project root, with floodsight conda env active):
    # Dry run — prints the message, sends nothing
    python scripts/send_morning_briefing.py --dry-run

    # Live send (requires AT env vars set)
    python scripts/send_morning_briefing.py

    # Point at a different API (e.g. local dev)
    python scripts/send_morning_briefing.py --api http://localhost:8080

Environment variables (set in your shell, .env file, or GitHub Secrets):
    AT_USERNAME      Africa's Talking username (use 'sandbox' for testing)
    AT_API_KEY       Africa's Talking API key
    AT_SENDER_ID     Registered short-code / sender name (optional)
    SUPABASE_URL     Supabase project URL (required for live subscriber sends)
    SUPABASE_KEY     Supabase service-role key
    FLOODSIGHT_API   Base URL of the deployed API
                     (default: https://floodsight-starter.onrender.com)

Scheduled automatically at 05:00 UTC (06:00 WAT) via GitHub Actions.
See .github/workflows/morning_briefing.yml
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
import urllib.request
from pathlib import Path

# Make `floodsight` importable when the script is run directly
# (Python adds scripts/ to sys.path, not the project root)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from datetime import datetime, timezone, timedelta

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

DEFAULT_API = "https://floodsight-starter.onrender.com"

# Phase 13: city-wide coverage — 15 LGAs.
# Area labels used in the SMS depending on where alerts are concentrated.
HIGH_DENSITY_AREAS  = "Alimosho, Kosofe, Mushin, Oshodi-Isolo"  # mainland core
COASTAL_AREAS       = "Eti-Osa, Lagos Island, Amuwo-Odofin, Ojo"  # coastal/island
NORTH_AREAS         = HIGH_DENSITY_AREAS   # backward-compat alias
SOUTH_AREAS         = COASTAL_AREAS        # backward-compat alias


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_summary(api_base: str, max_attempts: int = 3) -> dict:
    """
    Fetch /forecast/summary with retries and a generous timeout.

    Render free tier can take 30–90 s to cold-start after an idle night,
    which exceeds a single-attempt 60 s timeout.  We retry up to 3 times
    with 20 s gaps so the server has time to wake up between attempts.
    """
    import requests as _requests

    url = f"{api_base.rstrip('/')}/forecast/summary"
    headers = {"User-Agent": "FloodSight-Briefing/1.0"}

    for attempt in range(1, max_attempts + 1):
        try:
            log.info("Fetching %s (attempt %d/%d)", url, attempt, max_attempts)
            resp = _requests.get(url, headers=headers, timeout=90)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            if attempt < max_attempts:
                wait = 20 * attempt   # 20 s, then 40 s
                log.warning("Attempt %d failed (%s) — retrying in %d s", attempt, exc, wait)
                time.sleep(wait)
            else:
                raise RuntimeError(
                    f"Failed to fetch forecast summary after {max_attempts} attempts: {exc}"
                ) from exc


# ---------------------------------------------------------------------------
# Format
# ---------------------------------------------------------------------------

def format_message(summary: dict) -> str:
    """
    Formats the briefing SMS.  Kept ≤ 160 chars so it fits in one SMS segment.
    """
    fc       = summary["forecast"]
    counts   = summary["alert_counts"]
    highest  = summary["highest_alert"]

    # Lagos time = UTC+1
    now_wat = datetime.now(timezone(timedelta(hours=1)))
    date_str = now_wat.strftime("%d %b %Y")
    r24      = round(fc["rain_24h_mm"])
    r72      = round(fc["rain_72h_mm"])

    if highest == "No Alert":
        msg = (
            f"FloodSight Lagos {date_str}\n"
            f"STATUS: No rule alert\n"
            f"Rain: {r24}mm/24h, {r72}mm/72h\n"
            f"No rule alert; flooding is still possible. Stay prepared."
        )
    else:
        lines = [f"FloodSight Lagos {date_str}", f"STATUS: {highest.upper()}"]

        warn = counts.get("Warning", 0)
        watch = counts.get("Watch", 0)
        if warn:
            lines.append(f"WARNING: {warn:,} grid cells")
        if watch:
            lines.append(f"WATCH: {watch:,} grid cells")

        lines.append(f"Rain: {r24}mm/24h, {r72}mm/72h")

        # Use actual alert-area data, never infer place names from cell counts.
        areas = list((summary.get('lga_alerts') or {}).keys())[:3]
        if areas:
            lines.append(f"Alert areas: {', '.join(areas)}")
        lines.append("Avoid flooded roads. Stay safe.")

        msg = "\n".join(lines)

    # Coastal surge advisory (P2 item 8).
    # Only the SURGE tier (>= 1.20 m) adds a line. The high-tide tier is
    # deliberately silent here: on its own it is a predictable spring tide,
    # which previously put a "HIGH TIDE ... expect possible tidal flooding"
    # line into ~50 briefings a year. When high tide coincides with rain it
    # already escalates the alert level itself (see marine.coastal_upgrade).
    coastal = summary.get("coastal") or {}
    if coastal.get("advisory"):
        msg += (
            f"\nCOASTAL SURGE: sea level peaks {coastal['max_sea_level_m']}m. "
            "Coastal areas: expect possible tidal flooding."
        )

    # Ogun dam-release advisory (P2 item 8 — Open-Meteo Flood/GloFAS)
    dam = summary.get("dam") or {}
    if dam.get("advisory"):
        msg += (
            f"\nOGUN RIVER: discharge forecast {dam['max_discharge_m3s']:.0f}m3/s "
            f"(peak {dam['peak_day']}). Low-lying areas near Ogun at risk."
        )

    # Warn if we're close to SMS limit so we can shorten if needed
    if len(msg) > 160:
        log.warning("Message is %d chars (>160). May use 2 SMS segments.", len(msg))

    return msg


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="FloodSight morning briefing sender")
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print message without reading private recipients or sending."
    )
    parser.add_argument(
        "--api",
        default=os.environ.get("FLOODSIGHT_API", DEFAULT_API),
        help=f"FloodSight API base URL (default: {DEFAULT_API})"
    )
    args = parser.parse_args()

    # The morning cron used to bypass the resident dispatch approval entirely.
    if not args.dry_run and os.getenv("BRIEFING_DISPATCH_ENABLED", "false").lower() != "true":
        log.error("Morning SMS awaits pilot approval and BRIEFING_DISPATCH_ENABLED=true.")
        sys.exit(1)

    # Idempotency guard: if this is a backup/retry run and the briefing was
    # already sent today (logged in Supabase), skip to avoid double-sending.
    if not args.dry_run and os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        try:
            from floodsight.db.supabase_client import briefing_sent_today
            if briefing_sent_today():
                log.info("Briefing already sent today (Lagos time) — skipping. "
                         "This backup run is not needed.")
                return
        except Exception as exc:
            log.error("Could not check briefing ledger; refusing possible duplicate send.")
            sys.exit(1)

    # Live recipient discovery must use active subscribers with recorded consent.
    # Dry runs deliberately do not read private recipients.
    recipients: list[str] = []
    subscribers: list[dict] = []
    recipients_source = "none (read-only)" if args.dry_run else "active subscribers with recorded consent"
    if not args.dry_run and os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        try:
            from floodsight.db.supabase_client import get_active_subscribers

            subscribers = get_active_subscribers()
            if any(not s.get('id') or not s.get('phone') or not s.get('consent_at') for s in subscribers):
                raise RuntimeError('Subscriber identity or consent missing')
            recipients = [s["phone"] for s in subscribers]
            recipients_source = f"supabase ({len(recipients)} active subscribers)"
        except Exception as exc:
            log.error("Subscriber lookup failed; refusing fallback recipients.")
            sys.exit(1)
    elif not args.dry_run:
        log.error("Durable subscriber store is required; refusing fallback recipients.")
        sys.exit(1)

    log.info("Recipients source: %s", recipients_source)

    if not recipients and not args.dry_run:
        log.info("No active subscribers with recorded consent; no briefing sent.")
        return

    # Fetch forecast
    try:
        summary = fetch_summary(args.api)
    except RuntimeError as exc:
        log.error("%s", exc)
        sys.exit(1)

    log.info(
        "Forecast: %s | Warning=%d Watch=%d No Alert=%d",
        summary["highest_alert"],
        summary["alert_counts"].get("Warning", 0),
        summary["alert_counts"].get("Watch", 0),
        summary["alert_counts"].get("No Alert", 0),
    )

    # Format
    message = format_message(summary)

    print(f"\n{'='*50}")
    print(f"MESSAGE ({len(message)} chars):")
    print(message)
    print(f"{'='*50}")
    print(f"RECIPIENT COUNT: {len(recipients)} (phone numbers omitted)")
    print()

    # Send
    if args.dry_run:
        log.info("Dry run — no message sent.")
        return

    # Reuse the durable claim RPC with a separate Briefing namespace. Claim
    # before contacting the provider; retain claims even on ambiguous failures.
    # A failed ledger write or a backup run cannot automatically resend them.
    try:
        recipients = reserve_briefing_recipients(subscribers)
    except Exception:
        log.error("Could not reserve briefing recipients. No provider call made; inspect partial claims before retry.")
        sys.exit(1)
    if not recipients:
        log.info("All briefing recipients already reserved today; no provider call made.")
        return

    from floodsight.notifications.africastalking import send_sms
    try:
        send_sms(message, recipients)
        log.info("Provider request completed; final handset delivery remains unverified.")
    except (ValueError, RuntimeError) as exc:
        log.error("Provider call failed. Retain briefing claims and review provider outcomes before retry.")
        sys.exit(1)

    # Log the send so backup cron runs don't double-send
    if os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_KEY"):
        try:
            from floodsight.db.supabase_client import log_briefing_sent
            log_briefing_sent(len(recipients), dry_run=False)
        except Exception as exc:
            log.error("Provider request completed but briefing ledger write failed. Operator review required before any retry.")
            sys.exit(1)


def reserve_briefing_recipients(subscribers: list[dict]) -> list[str]:
    from floodsight.db.supabase_client import claim_alert, today_lagos
    event_date = today_lagos()
    return [subscriber['phone'] for subscriber in subscribers
            if claim_alert(subscriber['id'], event_date, 'Briefing')]


if __name__ == "__main__":
    main()
