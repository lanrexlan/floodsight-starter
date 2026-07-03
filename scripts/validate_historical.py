"""
FloodSight historical validation — Phase 10.

Back-tests the FloodSight alert engine against documented Lagos flood events
using real historical rainfall from the Open-Meteo archive API (free, no key).

Usage (from project root, with floodsight conda env active):
    python scripts/validate_historical.py

    # Hit the deployed API instead of running the engine locally
    python scripts/validate_historical.py --api https://floodsight-starter.onrender.com

Output: a table printed to the terminal and a JSON summary saved to
        outputs/validation_results.json
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import urllib.request
from pathlib import Path

# Ensure project root is on sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(message)s")
log = logging.getLogger(__name__)

API_DEFAULT = "https://floodsight-starter.onrender.com"

# ── ANSI colours ──────────────────────────────────────────────────
GREEN  = "\033[92m"
AMBER  = "\033[93m"
RED    = "\033[91m"
RESET  = "\033[0m"
BOLD   = "\033[1m"
DIM    = "\033[2m"


def colour_alert(level: str, text: str = "") -> str:
    label = text or level
    if level == "Warning": return f"{RED}{label}{RESET}"
    if level == "Watch":   return f"{AMBER}{label}{RESET}"
    return f"{GREEN}{label}{RESET}"


def tick_cross(correct: bool) -> str:
    return f"{GREEN}✓{RESET}" if correct else f"{RED}✗{RESET}"


# ── Fetch validation results from the API ────────────────────────

def fetch_from_api(api_base: str) -> dict:
    url = f"{api_base.rstrip('/')}/validate/events"
    log.info("Fetching %s", url)
    req = urllib.request.Request(url, headers={"User-Agent": "FloodSight-Validate/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp:
        return json.loads(resp.read())


# ── Run locally (same logic as the API router) ───────────────────

def run_locally() -> dict:
    from api.routers.validate import _compute_results, FLOOD_EVENTS
    log.info("Running validation locally against the risk grid …")
    results = _compute_results()
    total   = len(results)
    correct = sum(1 for r in results if r["correct"])
    return {
        "events": results,
        "summary": {
            "total_events": total,
            "correct":      correct,
            "accuracy_pct": round(correct / total * 100) if total else 0,
        },
    }


# ── Print report ─────────────────────────────────────────────────

def print_report(data: dict) -> None:
    events  = data["events"]
    summary = data["summary"]

    col_w = [30, 13, 13, 14, 14, 8, 5]
    header = ["Event", "24h Rain", "3-day Rain", "Reported", "FloodSight", "Correct", "%Warn"]
    sep    = "─" * (sum(col_w) + len(col_w) * 3 + 1)

    print(f"\n{BOLD}FloodSight Historical Validation{RESET}")
    print(f"{DIM}Real rainfall (Open-Meteo archive) vs. documented Lagos flood events{RESET}\n")
    print(sep)
    print("  ".join(h.ljust(w) for h, w in zip(header, col_w)))
    print(sep)

    for r in events:
        name    = r["name"][:28]
        r24     = f"{r['rain_24h_mm']} mm"
        r72     = f"{r['rain_72h_mm']} mm"
        rep     = colour_alert(r["reported_severity"])
        pred    = colour_alert(r["predicted_alert"])
        correct = tick_cross(r["correct"])
        warn_pct = f"{r['warning_pct']}%"
        row = [name, r24, r72, rep, pred, correct, warn_pct]
        print("  ".join(v.ljust(w) for v, w in zip(row, col_w)))

    print(sep)
    acc   = summary["accuracy_pct"]
    total = summary["total_events"]
    ok    = summary["correct"]
    colour = GREEN if acc >= 80 else (AMBER if acc >= 60 else RED)
    print(f"\n{BOLD}Result: {colour}{ok}/{total} events correctly flagged ({acc}%){RESET}\n")

    if acc >= 80:
        print(f"{GREEN}✓ Strong predictive skill — FloodSight consistently identified major flood events.{RESET}")
    elif acc >= 60:
        print(f"{AMBER}~ Moderate skill — some events detected; threshold tuning recommended.{RESET}")
    else:
        print(f"{RED}✗ Below expectation — review alert thresholds in floodsight/config.py.{RESET}")
    print()


# ── Save JSON ────────────────────────────────────────────────────

def save_json(data: dict) -> None:
    out_dir = Path(__file__).resolve().parent.parent / "outputs"
    out_dir.mkdir(exist_ok=True)
    path = out_dir / "validation_results.json"
    with open(path, "w") as f:
        json.dump(data, f, indent=2)
    log.info("Results saved to %s", path)


# ── Main ─────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="FloodSight historical validation")
    parser.add_argument(
        "--api", default=None,
        help="If provided, fetch results from the deployed API instead of running locally."
    )
    args = parser.parse_args()

    if args.api:
        try:
            data = fetch_from_api(args.api)
        except Exception as exc:
            log.error("API fetch failed: %s", exc)
            sys.exit(1)
    else:
        data = run_locally()

    print_report(data)
    save_json(data)


if __name__ == "__main__":
    main()
