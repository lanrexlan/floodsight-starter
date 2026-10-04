#!/usr/bin/env python3
"""
Recalibrate the two-tier coastal signal against the full available record.

Reproduces the October 2026 calibration documented in
floodsight/forecast/marine.py. Re-run it as the record grows, or after any
change to the monitoring points, and update COASTAL_SURGE_M /
COASTAL_HIGH_TIDE_M if the recommendation moves.

What it does
------------
1. Pulls hourly sea_level_height_msl for every monitoring point in
   marine.COAST_POINTS from the first year with data to yesterday, using the
   SAME Open-Meteo model the live signal uses (no `models=` override — the
   `era5_ocean` model returns no sea level at all).
2. Takes the daily maximum across all points, then the 72-hour look-ahead
   maximum, because that is what the live advisory evaluates.
3. Reports the distribution, how many days per year each candidate threshold
   would be active, the top days (to check they are equinox spring tides
   rather than surges), and seasonality.
4. Recommends:
     surge tier     = just above the record maximum  (tide alone never reaches it)
     high-tide tier = ~96th percentile of the 72 h max (~15 days/yr)

Usage (from the project root, needs internet):
    python scripts/calibrate_coastal_threshold.py
    python scripts/calibrate_coastal_threshold.py --start-year 2023 --csv out.csv

Limitation: this controls the FALSE-ALARM rate. It cannot test detection of
a real surge unless one falls inside the record. Pair it with tide-gauge data
(NiHSA) when available.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.request
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from floodsight.forecast.marine import (  # noqa: E402
    COAST_POINTS,
    COASTAL_HIGH_TIDE_M,
    COASTAL_SURGE_M,
)

URL = ("https://marine-api.open-meteo.com/v1/marine?latitude={lat}&longitude={lon}"
       "&hourly=sea_level_height_msl&start_date={sd}&end_date={ed}&timezone=Africa%2FLagos")
CANDIDATES = [0.90, 0.95, 1.00, 1.05, 1.10, 1.15, 1.20, 1.25]
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()


def fetch(lat: float, lon: float, sd: str, ed: str) -> tuple[list[str], list[float | None]]:
    req = urllib.request.Request(URL.format(lat=lat, lon=lon, sd=sd, ed=ed),
                                 headers={"User-Agent": "FloodSight/1.0"})
    with urllib.request.urlopen(req, timeout=60) as r:
        h = json.load(r).get("hourly", {})
    return h.get("time", []), h.get("sea_level_height_msl", [])


def quantile(sorted_vals: list[float], p: float) -> float:
    return sorted_vals[min(len(sorted_vals) - 1, int(p * len(sorted_vals)))]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("--start-year", type=int, default=2023)
    ap.add_argument("--csv", help="optional path to write the daily-max series")
    args = ap.parse_args()

    end = date.today() - timedelta(days=1)
    daily: dict[str, float] = {}
    for lat, lon, label in COAST_POINTS:
        n = 0
        for yr in range(args.start_year, end.year + 1):
            sd = f"{yr}-01-01"
            ed = min(date(yr, 12, 31), end).isoformat()
            times, heights = fetch(lat, lon, sd, ed)
            for t, h in zip(times, heights):
                if h is None:
                    continue
                n += 1
                k = t[:10]
                if k not in daily or h > daily[k]:
                    daily[k] = h
        print(f"  {label:<20} {n:>7,} hourly values")

    if not daily:
        print("No sea-level data returned. Check the date range and network.")
        return 1

    days = sorted(daily)
    vals = [daily[d] for d in days]
    window = [max(vals[i:i + 3]) for i in range(len(vals))]  # 72 h look-ahead
    years = len(vals) / 365.25
    sv, sw = sorted(vals), sorted(window)

    print(f"\nRecord: {days[0]} to {days[-1]} — {len(vals):,} days ({years:.2f} yr)")
    print("Daily max: " + "  ".join(f"p{int(p*100)} {quantile(sv, p):.2f}"
                                     for p in (0.5, 0.9, 0.95, 0.99)) + f"  max {sv[-1]:.2f} m")

    print("\nDays ACTIVE per year (72 h look-ahead):")
    for t in CANDIDATES:
        k = sum(1 for x in window if x >= t)
        marks = []
        if math.isclose(t, COASTAL_SURGE_M):
            marks.append("current surge tier")
        if math.isclose(t, COASTAL_HIGH_TIDE_M):
            marks.append("current high-tide tier")
        print(f"  {t:.2f} m  {k:>4} days  {k/years:5.1f}/yr  {100*k/len(window):4.1f}%"
              + (f"   <- {', '.join(marks)}" if marks else ""))

    print("\nTop 10 days (equinox dates => astronomical tide, not surge):")
    for d, v in sorted(zip(days, vals), key=lambda p: -p[1])[:10]:
        print(f"  {d}  {v:.2f} m")

    by_month: dict[int, int] = defaultdict(int)
    for d, w in zip(days, window):
        if w >= COASTAL_HIGH_TIDE_M:
            by_month[int(d[5:7]) - 1] += 1
    print(f"\nHigh-tide-tier days by month: "
          + " ".join(f"{MONTHS[m]} {by_month[m]}" for m in range(12)))

    # round() before ceil(): (1.10 + 0.05) * 20 == 23.000000000000004 would
    # otherwise ceil to 24 and recommend 1.20 instead of 1.15.
    rec_surge = math.ceil(round((sv[-1] + 0.05) * 20, 6)) / 20   # >= max + 5 cm, 0.05 steps
    rec_tide = round(quantile(sw, 0.96) * 20) / 20
    print(f"\nRecommendation:  COASTAL_SURGE_M = {rec_surge:.2f}   "
          f"COASTAL_HIGH_TIDE_M = {rec_tide:.2f}")
    print(f"Current:         COASTAL_SURGE_M = {COASTAL_SURGE_M:.2f}   "
          f"COASTAL_HIGH_TIDE_M = {COASTAL_HIGH_TIDE_M:.2f}")

    if args.csv:
        with open(args.csv, "w") as fh:
            fh.write("date,daily_max_sea_level_m,max_72h_m\n")
            for d, v, w in zip(days, vals, window):
                fh.write(f"{d},{v:.2f},{w:.2f}\n")
        print(f"\nWrote {args.csv}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
