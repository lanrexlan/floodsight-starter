#!/usr/bin/env python3
"""
FloodSight MEL — Monthly DHIS2 Malaria Case Data Pull.

Fetches malaria case counts from the DHIS2 Nigeria / LSPHCDA instance and
stores them in the dhis2_malaria_cases Supabase table for the health dashboard
and NEXA outcome analysis.

Schedule: run on the 1st of each month (manually or via cron).

Usage
-----
    # Pull last completed month (auto-detected):
    python scripts/mel_dhis2_pull.py

    # Pull a specific month:
    python scripts/mel_dhis2_pull.py --period 202506

    # Pull specific LGAs only:
    python scripts/mel_dhis2_pull.py --period 202506 --lgas Alimosho Kosofe

    # Test DHIS2 connectivity without pulling data:
    python scripts/mel_dhis2_pull.py --test-connection

    # Preview what would be pulled (no DB write):
    python scripts/mel_dhis2_pull.py --period 202506 --dry-run

Prerequisites
-------------
    DHIS2_BASE_URL, DHIS2_USERNAME, DHIS2_PASSWORD environment variables set.
    LGA_ORG_UNIT_MAP in dhis2_client.py populated with real DHIS2 UIDs.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
log = logging.getLogger("mel_dhis2_pull")


def _last_completed_month() -> str:
    """Return the DHIS2 period string for the most recently completed month."""
    today = date.today()
    if today.month == 1:
        return f"{today.year - 1}12"
    return f"{today.year}{today.month - 1:02d}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Pull malaria case data from DHIS2 into FloodSight Supabase"
    )
    parser.add_argument(
        "--period",
        default=None,
        help="DHIS2 period string e.g. 202506 (default: last completed month)",
    )
    parser.add_argument(
        "--lgas",
        nargs="*",
        default=None,
        help="LGA names to pull (default: all 15 AOI LGAs)",
    )
    parser.add_argument(
        "--test-connection",
        action="store_true",
        help="Test DHIS2 connectivity and exit",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch from DHIS2 but do not write to Supabase",
    )
    args = parser.parse_args()

    # ------------------------------------------------------------------
    # Connection test
    # ------------------------------------------------------------------
    if args.test_connection:
        from floodsight.health.dhis2_client import test_connection
        ok = test_connection()
        return 0 if ok else 1

    # ------------------------------------------------------------------
    # Determine period
    # ------------------------------------------------------------------
    period = args.period or _last_completed_month()
    log.info("Pulling DHIS2 malaria data for period: %s", period)

    # ------------------------------------------------------------------
    # Pull from DHIS2
    # ------------------------------------------------------------------
    from floodsight.health.dhis2_client import pull_malaria_cases

    try:
        rows = pull_malaria_cases(period, lga_names=args.lgas)
    except RuntimeError as exc:
        log.error("DHIS2 configuration error: %s", exc)
        return 1
    except Exception as exc:
        log.error("DHIS2 pull failed: %s", exc)
        return 1

    if not rows:
        log.warning(
            "No data returned. Either the DHIS2 org unit / data element UIDs "
            "are still placeholders, or the period has no data yet."
        )
        return 0

    log.info("Retrieved %d LGA rows from DHIS2:", len(rows))
    for r in rows:
        log.info(
            "  %-22s confirmed=%s  suspected=%s  rdt_pos=%s  treated=%s",
            r["lga_name"],
            r.get("confirmed_cases"),
            r.get("suspected_cases"),
            r.get("rdt_positive"),
            r.get("treatment_started"),
        )

    if args.dry_run:
        log.info("[DRY RUN] Would upsert %d rows — skipping Supabase write.", len(rows))
        return 0

    # ------------------------------------------------------------------
    # Upsert into Supabase (on_conflict = lga_name + period)
    # ------------------------------------------------------------------
    from floodsight.db.supabase_client import _get_client

    client = _get_client()
    success = 0
    errors  = 0

    for row in rows:
        try:
            (
                client.table("dhis2_malaria_cases")
                .upsert(row, on_conflict="lga_name,period")
                .execute()
            )
            success += 1
        except Exception as exc:
            log.error("Failed to upsert %s: %s", row.get("lga_name"), exc)
            errors += 1

    log.info(
        "DHIS2 pull complete: %d rows upserted, %d errors",
        success, errors,
    )
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
