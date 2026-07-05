#!/usr/bin/env python3
"""
Probe Open-Meteo Flood and Marine APIs for the 4 remaining FloodSight failures.
Run from project root:  python scripts/probe_signals.py
"""
import json, urllib.request
from datetime import date, timedelta

EVENTS = [
    ("2022_10 Dam-Release",     "2022-10-12"),
    ("2021_07a Tidal-Rain",     "2021-07-10"),
    ("2016_07 Coastal",         "2016-07-19"),
    ("2019_07 Localized storm", "2019-07-08"),
]
DAM_LAT,   DAM_LON   = 6.67, 3.43
COAST_LAT, COAST_LON = 6.30, 3.35

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight/1.0"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.loads(r.read())

for name, peak in EVENTS:
    d = date.fromisoformat(peak)
    print()
    print("=" * 60)
    print("Event:", name, " ", peak)

    # GloFAS river discharge at Ogun/Isheri
    start = (d - timedelta(days=5)).isoformat()
    end   = (d + timedelta(days=2)).isoformat()
    url = (
        "https://flood-api.open-meteo.com/v1/flood"
        "?latitude=" + str(DAM_LAT) + "&longitude=" + str(DAM_LON)
        + "&daily=river_discharge"
        + "&start_date=" + start + "&end_date=" + end
    )
    try:
        data = fetch(url)
        flows = [(t, q) for t, q in zip(data["daily"]["time"], data["daily"]["river_discharge"]) if q is not None]
        max_q = max(q for _, q in flows) if flows else 0
        peak_day = max(flows, key=lambda p: p[1])[0] if flows else "N/A"
        print("  Dam (Ogun Isheri): max=" + str(round(max_q, 1)) + " m3/s on " + peak_day + "  (threshold=300)")
        for t, q in flows:
            print("    " + t + ": " + str(round(q, 1)) + " m3/s")
    except Exception as e:
        print("  Dam fetch FAILED:", e)

    # ERA5-Ocean sea level at Lagos coast
    start = (d - timedelta(days=1)).isoformat()
    end   = (d + timedelta(days=3)).isoformat()
    url = (
        "https://marine-api.open-meteo.com/v1/marine"
        "?latitude=" + str(COAST_LAT) + "&longitude=" + str(COAST_LON)
        + "&hourly=sea_level_height_msl"
        + "&models=era5_ocean"
        + "&start_date=" + start + "&end_date=" + end
    )
    try:
        data = fetch(url)
        heights = [h for h in data["hourly"].get("sea_level_height_msl", []) if h is not None]
        if heights:
            mn, mx, avg = min(heights), max(heights), sum(heights)/len(heights)
            print("  Coastal ERA5-Ocean: min=" + str(round(mn,3)) + "  max=" + str(round(mx,3)) + "  mean=" + str(round(avg,3)) + " m  (threshold=1.0)")
            # Print hourly values so we can see the surge profile
            times = data["hourly"]["time"]
            for t, h in zip(times, data["hourly"]["sea_level_height_msl"])[:24]:
                if h is not None:
                    print("    " + t + ": " + str(round(h,3)) + " m")
        else:
            print("  Coastal ERA5-Ocean: no data returned")
    except Exception as e:
        print("  Coastal fetch FAILED:", e)
