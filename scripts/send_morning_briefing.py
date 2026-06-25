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
    AT_RECIPIENTS    Comma-separated E.164 numbers: +2348012345678,+2349012345678
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
import urllib.request
from pathlib import Path

# Make `floodsight` importable when the script is run directly
# (Python adds scripts/ to sys.path, not the project root)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from datetime import datetime, timezone

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

DEFAULT_API = "https://floodsight-starter.onrender.com"

# Areas within the pilot grid for context (north cluster, where most cells are)
NORTH_AREAS = "Kosofe, Gbagada, Ketu, Ojota"
SOUTH_AREAS = "Lagos Island"


# ---------------------------------------------------------------------------
# Fetch
# ---------------------------------------------------------------------------

def fetch_summary(api_base: str) -> dict:
    url = f"{api_base.rstrip('/')}/forecast/summary"
    log.info("Fetching %s", url)
    req = urllib.request.Request(
        url, headers={"User-Agent": "FloodSight-Briefing/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            return json.loads(resp.read())
    except Exception as exc:
        raise RuntimeError(f"Failed to fetch forecast summary: {exc}") from exc


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
    now_utc  = datetime.now(timezone.utc)
    date_str = now_utc.strftime("%d %b %Y")
    r24      = round(fc["rain_24h_mm"])
    r72      = round(fc["rain_72h_mm"])

    if highest == "No Alert":
        msg = (
            f"FloodSight Lagos {date_str}\n"
            f"STATUS: All Clear\n"
            f"Rain: {r24}mm/24h, {r72}mm/72h\n"
            f"No active flood alerts. Stay prepared."
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

        # Mention affected pilot areas
        areas = NORTH_AREAS if warn + watch > 1000 else SOUTH_AREAS
        lines.append(f"Areas: {areas}")
        lines.append("Avoid flooded roads. Stay safe.")

        msg = "\n".join(lines)

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
        help="Print message and recipients without actually sending."
    )
    parser.add_argument(
        "--api",
        default=os.environ.get("FLOODSIGHT_API", DEFAULT_API),
        help=f"FloodSight API base URL (default: {DEFAULT_API})"
    )
    args = parser.parse_args()

    # Parse recipients
    recipients_raw = os.environ.get("AT_RECIPIENTS", "")
    recipients = [r.strip() for r in recipients_raw.split(",") if r.strip()]

    if not recipients and not args.dry_run:
        log.error(
            "AT_RECIPIENTS is not set. "
            "Set it to comma-separated E.164 numbers, e.g. +2348012345678"
        )
        sys.exit(1)

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
    print(f"RECIPIENTS: {recipients if recipients else '(none — dry run)'}")
    print()

    # Send
    if args.dry_run:
        log.info("Dry run — no message sent.")
        return

    from floodsight.notifications.africastalking import send_sms
    try:
        result = send_sms(message, recipients)
        log.info("Send result: %s", result)
    except (ValueError, RuntimeError) as exc:
        log.error("Send failed: %s", exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
