#!/usr/bin/env python3
"""
FloodSight Health Alerts — Daily CHEW Dispatch Script.

Runs at 07:30 WAT (06:30 UTC) daily via GitHub Actions health_alerts.yml,
30 minutes before the resident flood briefing.

Only sends health alerts when:
  1. At least one pilot LGA has a Watch or Warning flood alert today
  2. The outbreak probability for that LGA is Moderate or above
  3. Alert has not already been sent today (idempotency via Supabase)

Usage (manual / testing):
    python scripts/send_health_alerts.py
    python scripts/send_health_alerts.py --dry-run

Environment variables required:
    SUPABASE_URL, SUPABASE_KEY           — Supabase service-role credentials
    AT_USERNAME                          — Africa's Talking username
    AT_API_KEY                           — Africa's Talking API key

Optional:
    FLOODSIGHT_API                       — base URL of the deployed API
                                           (default: https://floodsight-starter.onrender.com)
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path
from datetime import date

# Make the floodsight package importable when the script is run directly
# (Python adds scripts/ to sys.path, not the project root).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("health_alerts")

PILOT_LGAS = {"Alimosho", "Ajeromi-Ifelodun", "Kosofe", "Oshodi-Isolo", "Ikorodu"}


def main(dry_run: bool = False) -> int:
    log.info("=== FloodSight Health Alerts — %s%s ===",
             date.today().isoformat(), " [DRY RUN]" if dry_run else "")

    # ------------------------------------------------------------------
    # 1. Fetch current alert grid from the running API
    # ------------------------------------------------------------------
    import os
    import requests

    base_url = os.getenv("FLOODSIGHT_API", "https://floodsight-starter.onrender.com").rstrip("/")
    log.info("Fetching alert grid from %s/forecast/alerts", base_url)

    try:
        resp = requests.get(f"{base_url}/forecast/alerts", timeout=60)
        resp.raise_for_status()
        alert_data = resp.json()
    except Exception as exc:
        log.error("Failed to fetch alert grid: %s", exc)
        return 1

    alert_levels: list[str] = alert_data.get("alert_levels", [])
    highest = alert_data.get("highest_alert", "No Alert")

    log.info("Alert grid fetched: %d cells, highest=%s", len(alert_levels), highest)

    # ------------------------------------------------------------------
    # 2. Fetch the grid GeoJSON to get lga_name + hazard_score per cell
    # ------------------------------------------------------------------
    try:
        grid_resp = requests.get(f"{base_url}/risk/grid", timeout=60)
        grid_resp.raise_for_status()
        grid_geojson = grid_resp.json()
    except Exception as exc:
        log.error("Failed to fetch risk grid: %s", exc)
        return 1

    # ------------------------------------------------------------------
    # 3. Derive the highest alert level per pilot LGA
    #
    # This used to read alert_data["lga_alerts"], but that field maps
    # lga_name -> COUNT OF ALERTING CELLS (an int, e.g. {"Kosofe": 980}),
    # not lga_name -> alert level. The old comparison
    #     level in ("Watch", "Warning")
    # therefore compared an int against strings, never matched, and the
    # script exited at "No pilot LGAs at Watch/Warning today" on every run
    # — which is why no CHEW SMS was ever sent. lga_alerts is also
    # truncated to the top 6 LGAs, so pilot LGAs could be dropped entirely.
    #
    # Deriving the level from alert_levels + the grid features is exact and
    # covers all 15 LGAs.
    # ------------------------------------------------------------------
    _RANK = {"No Alert": 0, "Watch": 1, "Warning": 2}
    features = grid_geojson.get("features", [])

    if len(features) != len(alert_levels):
        log.warning(
            "Grid/alert length mismatch: %d features vs %d alert levels — "
            "comparing the overlapping prefix only",
            len(features), len(alert_levels),
        )

    lga_highest: dict[str, str] = {}
    for i in range(min(len(features), len(alert_levels))):
        lga   = str(features[i].get("properties", {}).get("lga_name", "")).strip()
        level = alert_levels[i]
        if not lga or lga == "nan":
            continue
        if _RANK.get(level, 0) > _RANK.get(lga_highest.get(lga, "No Alert"), 0):
            lga_highest[lga] = level

    log.info(
        "Pilot LGA alert levels: %s",
        {k: v for k, v in lga_highest.items() if k in PILOT_LGAS},
    )

    active_pilot_lgas = {
        lga: level for lga, level in lga_highest.items()
        if lga in PILOT_LGAS and level in ("Watch", "Warning")
    }

    if not active_pilot_lgas:
        log.info(
            "No pilot LGAs at Watch/Warning today — no health alerts needed. Exiting."
        )
        return 0

    log.info("Active pilot LGAs: %s", active_pilot_lgas)

    # ------------------------------------------------------------------
    # 4. Score outbreak probability for each LGA
    # ------------------------------------------------------------------
    from floodsight.health.engine import score_lgas

    event_id = date.today().isoformat()
    scores   = score_lgas(grid_geojson, alert_levels, flood_event_id=event_id)

    if not scores:
        log.info("No LGAs scored above inundation threshold — exiting.")
        return 0

    log.info("Scored %d LGAs:", len(scores))
    for s in scores:
        log.info(
            "  %-22s tier=%-8s prob=%.3f  area=%.2f km²  window=%s to %s",
            s["lga_name"], s["risk_tier"], s["outbreak_probability"],
            s["inundation_area_km2"], s["outbreak_window_start"], s["outbreak_window_end"],
        )

    if dry_run:
        log.info("[DRY RUN] Would store %d scores and dispatch alerts — skipping.", len(scores))
        return 0

    # ------------------------------------------------------------------
    # 5. Store scores in Supabase
    # ------------------------------------------------------------------
    from floodsight.db.supabase_client import upsert_lga_health_risk

    inserted = upsert_lga_health_risk(scores)
    risk_ids = {row["lga_name"]: row["id"] for row in inserted if row.get("id")}
    log.info("Stored %d health risk rows in Supabase", len(inserted))

    # ------------------------------------------------------------------
    # 6. Dispatch CHEW SMS alerts
    # ------------------------------------------------------------------
    from floodsight.health.chew_alerts import dispatch_health_alerts

    summary = dispatch_health_alerts(scores, risk_ids)
    log.info(
        "Dispatch complete: sent=%d  skipped_already_sent=%d  "
        "skipped_low_risk=%d  skipped_not_pilot=%d  failed=%d",
        summary["sent"],
        summary["skipped_already_sent"],
        summary["skipped_low_risk"],
        summary["skipped_not_pilot"],
        summary["failed"],
    )

    if summary["failed"] > 0:
        log.warning("%d alerts failed to send — check AT credentials and logs", summary["failed"])
        return 1

    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="FloodSight CHEW Health Alert Dispatcher")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Score LGAs and log what would be sent, but do not write to DB or send SMS",
    )
    args = parser.parse_args()
    sys.exit(main(dry_run=args.dry_run))
