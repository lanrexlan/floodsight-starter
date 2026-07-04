"""
scripts/10_augment_training_data.py  —  Phase 22 training data augmentation.

The existing real_training_dataset.csv has 616 rows from only ONE flood event
(Lekki 2024-07-03), all with identical rainfall values. This means the model
cannot learn how rainfall intensity affects flood depth — a key predictive
relationship. R² is therefore near zero on unseen data.

This script fixes that by:
  1. Taking each validated historical event from api/routers/validate.py
  2. Fetching the actual rainfall from Open-Meteo archive for that date
  3. Generating N synthetic rows per event by resampling the Lekki grid
     cell locations (same terrain features, event-specific rainfall)
  4. Assigning depth via a HAND-calibrated lognormal model scaled to
     the event's known flood severity
  5. Appending all new rows to real_training_dataset.csv
  6. Triggering the model retraining script

Usage:
    python scripts/10_augment_training_data.py
    python scripts/10_augment_training_data.py --dry-run   # preview only
    python scripts/10_augment_training_data.py --rows 80   # rows per event (default 60)
    python scripts/10_augment_training_data.py --no-retrain
"""

from __future__ import annotations

import argparse
import csv
import json
import logging
import os
import random
import subprocess
import sys
import time
import urllib.request
from datetime import date, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = ROOT / "data" / "processed" / "real_training_dataset.csv"

LAGOS_LAT = 6.5244
LAGOS_LON = 3.3792

# ── Historical events — identical to validate.py ──────────────────────────
# Only include rain-driven events; skip dam-release events (2019_10, 2022_10)
# because their low local rainfall would add misleading depth/rain pairs.
AUGMENT_EVENTS = [
    {"id": "2011_07", "peak_date": "2011-07-10", "severity": "Warning"},
    {"id": "2012_07", "peak_date": "2012-07-04", "severity": "Warning"},
    {"id": "2015_07", "peak_date": "2015-07-14", "severity": "Warning"},
    {"id": "2016_07", "peak_date": "2016-07-19", "severity": "Warning"},
    {"id": "2017_06", "peak_date": "2017-06-22", "severity": "Warning"},
    {"id": "2018_06", "peak_date": "2018-06-21", "severity": "Warning"},
    {"id": "2019_07", "peak_date": "2019-07-08", "severity": "Warning"},
    {"id": "2020_06", "peak_date": "2020-06-18", "severity": "Warning"},
    {"id": "2021_07a", "peak_date": "2021-07-10", "severity": "Warning"},
    {"id": "2021_07b", "peak_date": "2021-07-16", "severity": "Watch"},
    {"id": "2022_06", "peak_date": "2022-06-18", "severity": "Watch"},
    {"id": "2022_07", "peak_date": "2022-07-07", "severity": "Warning"},
    {"id": "2023_06", "peak_date": "2023-06-20", "severity": "Watch"},
    {"id": "2023_09", "peak_date": "2023-09-14", "severity": "Watch"},
    {"id": "2024_06", "peak_date": "2024-06-28", "severity": "Warning"},
    # 2024_07_03 is already in the CSV as lekki_2024_07_03 — skip to avoid duplication
]


# ── Open-Meteo rainfall fetch ──────────────────────────────────────────────

def fetch_rainfall(peak_date: str, retries: int = 4) -> tuple[float, float]:
    """Return (rain_24h_mm, rain_72h_mm) from Open-Meteo archive."""
    d     = date.fromisoformat(peak_date)
    start = (d - timedelta(days=2)).isoformat()
    url   = (
        "https://archive-api.open-meteo.com/v1/archive"
        f"?latitude={LAGOS_LAT}&longitude={LAGOS_LON}"
        f"&start_date={start}&end_date={peak_date}"
        "&daily=precipitation_sum&timezone=UTC"
    )
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight-Augment/1.0"})
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                data = json.loads(resp.read())
            break
        except Exception as exc:
            last = exc
            wait = 2 ** attempt
            log.warning("Archive attempt %d failed (%s) — retry in %ds", attempt + 1, exc, wait)
            time.sleep(wait)
    else:
        raise last

    precip   = [p or 0.0 for p in data["daily"]["precipitation_sum"]]
    rain_24h = precip[-1]
    rain_72h = sum(precip)
    return round(rain_24h, 1), round(rain_72h, 1)


# ── Depth generation ──────────────────────────────────────────────────────
# Depth is primarily governed by Height Above Nearest Drainage (HAND).
# Lower HAND → deeper flooding. We scale a lognormal sample by:
#   base_depth = lognormal(mu, sigma)          # event-severity baseline
#   depth = base_depth * exp(-hand_m * k)      # decay with HAND
#   depth = max(0.02, min(depth, 3.5))         # clamp to plausible range
#
# Known calibration anchors:
#   Warning event, HAND≈0-2m → observed depths 0.3-1.3m (Lekki 2024, FloodList)
#   Watch event,   HAND≈0-2m → observed depths 0.1-0.5m (FloodList July 2021)

def _depth_for_cell(hand_m: float, rain_24h: float, severity: str, rng: random.Random) -> float:
    """Sample a plausible flood depth for one cell given its HAND and the event severity."""
    if severity == "Warning":
        # Strong event: deeper baseline, steeper rain amplification
        mu    = -0.5 + 0.006 * rain_24h   # baseline shifts up with more rain
        sigma = 0.55
    else:  # Watch
        mu    = -1.0 + 0.004 * rain_24h
        sigma = 0.50

    import math
    base = math.exp(rng.gauss(mu, sigma))

    # HAND decay: k tuned so HAND=0 → ~full depth, HAND=5m → ~30% depth
    k     = 0.22
    depth = base * math.exp(-hand_m * k)

    # Minimum depth for a flooded cell: 2 cm
    depth = max(0.02, min(depth, 3.5))

    # Cells with HAND > 8m are very unlikely to flood — set near-zero
    if hand_m > 8.0:
        depth = rng.uniform(0.01, 0.05)

    return round(depth, 4)


# ── Load seed rows from existing CSV ─────────────────────────────────────

def load_seed_rows() -> list[dict]:
    """Load existing CSV rows to use as terrain feature seeds."""
    with open(CSV_PATH, newline="") as f:
        return list(csv.DictReader(f))


# ── Generate augmented rows for one event ────────────────────────────────

def generate_event_rows(
    event: dict,
    seed_rows: list[dict],
    rain_24h: float,
    rain_72h: float,
    n_rows: int,
    rng: random.Random,
) -> list[dict]:
    """Sample n_rows terrain rows and assign event-specific rainfall + depth."""
    # Skip if rainfall is too low to cause meaningful flooding
    # (ERA5 often underestimates convective Lagos storms, but if it shows <5mm
    #  we still generate rows with a minimum plausible rainfall to avoid
    #  training on "no rain → deep flood" contradictions)
    effective_24h = max(rain_24h, 15.0) if event["severity"] == "Warning" else max(rain_24h, 8.0)
    effective_72h = max(rain_72h, 40.0) if event["severity"] == "Warning" else max(rain_72h, 20.0)

    sampled = rng.choices(seed_rows, k=n_rows)
    new_rows = []
    for row in sampled:
        hand_m = float(row["hand_m"])
        depth  = _depth_for_cell(hand_m, effective_24h, event["severity"], rng)
        new_rows.append({
            "elevation_m":        row["elevation_m"],
            "slope_deg":          row["slope_deg"],
            "flow_accum":         row["flow_accum"],
            "hand_m":             row["hand_m"],
            "dist_to_water_m":    row["dist_to_water_m"],
            "landcover_class":    row["landcover_class"],
            "population_density": row["population_density"],
            "rain_24h_mm":        effective_24h,
            "rain_72h_mm":        effective_72h,
            "depth_m":            depth,
            "event":              event["id"],
            "event_name":         event["id"],
        })
    return new_rows


# ── Main ──────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Augment training data with historical events")
    parser.add_argument("--rows",       type=int,  default=60,    help="Rows per event (default 60)")
    parser.add_argument("--dry-run",    action="store_true",      help="Preview without writing")
    parser.add_argument("--no-retrain", action="store_true",      help="Skip retraining after augment")
    parser.add_argument("--seed",       type=int,  default=42,    help="RNG seed")
    args = parser.parse_args()

    rng = random.Random(args.seed)

    log.info("Loading seed rows from %s", CSV_PATH)
    seed_rows = load_seed_rows()
    log.info("  %d seed rows loaded", len(seed_rows))

    all_new_rows = []
    rain_results = []

    for event in AUGMENT_EVENTS:
        eid   = event["id"]
        pdate = event["peak_date"]

        log.info("Processing %s (%s)…", eid, pdate)
        try:
            rain_24h, rain_72h = fetch_rainfall(pdate)
            log.info("  Open-Meteo: 24h=%.1fmm  72h=%.1fmm", rain_24h, rain_72h)
        except Exception as exc:
            log.warning("  Rainfall fetch failed (%s) — using severity defaults", exc)
            rain_24h = 50.0 if event["severity"] == "Warning" else 25.0
            rain_72h = 100.0 if event["severity"] == "Warning" else 50.0

        rows = generate_event_rows(event, seed_rows, rain_24h, rain_72h, args.rows, rng)
        all_new_rows.extend(rows)
        rain_results.append({"id": eid, "rain_24h": rain_24h, "rain_72h": rain_72h, "rows": len(rows)})
        time.sleep(0.5)   # be polite to Open-Meteo

    log.info("Generated %d new rows across %d events", len(all_new_rows), len(AUGMENT_EVENTS))

    if args.dry_run:
        log.info("DRY RUN — not writing. Summary:")
        for r in rain_results:
            log.info("  %s: 24h=%.1fmm 72h=%.1fmm → %d rows", r["id"], r["rain_24h"], r["rain_72h"], r["rows"])
        return

    # Append to CSV
    fieldnames = [
        "elevation_m", "slope_deg", "flow_accum", "hand_m",
        "dist_to_water_m", "landcover_class", "population_density",
        "rain_24h_mm", "rain_72h_mm", "depth_m", "event", "event_name",
    ]
    import os, shutil
    tmp = CSV_PATH.with_suffix(".tmp")
    with open(CSV_PATH, newline="") as fin, open(tmp, "w", newline="") as fout:
        reader = csv.DictReader(fin)
        writer = csv.DictWriter(fout, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(reader)
        writer.writerows(all_new_rows)
    fout_fd = open(tmp, "rb")
    fout_fd.close()
    # fsync then replace
    with open(tmp, "rb") as f:
        data = f.read()
    with open(CSV_PATH, "wb") as f:
        f.write(data)
        f.flush()
        os.fsync(f.fileno())
    tmp.unlink(missing_ok=True)

    log.info("Appended %d rows to %s", len(all_new_rows), CSV_PATH)
    with open(CSV_PATH) as f:
        total = sum(1 for _ in f) - 1  # subtract header
    log.info("CSV now has %d data rows", total)

    if not args.no_retrain:
        log.info("Retraining model (--skip-gpkg)…")
        result = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "09_train_flood_depth.py"), "--skip-gpkg"],
            cwd=ROOT,
            capture_output=False,
        )
        if result.returncode != 0:
            log.error("Retraining exited with code %d", result.returncode)
            sys.exit(result.returncode)
        log.info("Retraining complete.")
    else:
        log.info("--no-retrain set; run: python scripts/09_train_flood_depth.py --skip-gpkg")


if __name__ == "__main__":
    main()
