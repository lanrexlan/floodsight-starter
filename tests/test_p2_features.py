"""
Tests for the P2 (missed-opportunity) features:

  * Inbound SMS keyword parsing (STOP/START/FLOOD/NOFLOOD) — /at/incoming
  * All Clear SMS template (single GSM-7 segment, opt-out intact)
  * OTP helpers (code hashing, requirement flag)
  * Coastal sea-level summariser (pure function, no network)
  * Morning-briefing coastal advisory line
"""

from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Inbound SMS parsing
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("STOP", ("stop", None)),
    (" stop ", ("stop", None)),
    ("Unsubscribe", ("stop", None)),
    ("STOP.", ("stop", None)),
    ("START", ("start", None)),
    ("resume", ("start", None)),
    ("FLOOD", ("flood", None)),
    ("flooded", ("flood", None)),
    ("FLOOD 0.5", ("flood", 0.5)),
    ("FLOOD 0.5M", ("flood", 0.5)),
    ("flood 50cm", ("flood", 0.5)),
    ("FLOOD 12", ("flood", None)),      # 12 m fails the sanity clamp
    ("NOFLOOD", ("dry", None)),
    ("no flood", ("dry", None)),
    ("DRY", ("dry", None)),
    ("hello there", ("unknown", None)),
    ("", ("unknown", None)),
])
def test_parse_inbound(text, expected):
    from api.routers.incoming import parse_inbound

    assert parse_inbound(text) == expected


# ---------------------------------------------------------------------------
# All Clear SMS template
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("area", [None, "Kosofe", "Ajeromi-Ifelodun", "X" * 120])
def test_all_clear_sms_single_segment(area):
    from floodsight.notifications.sms import _build_message, is_gsm7

    msg = _build_message("All Clear", area)
    assert len(msg) <= 160
    assert msg.endswith("Reply STOP to opt out")
    assert is_gsm7(msg)
    assert "All clear" in msg


def test_otp_sms_single_segment():
    from floodsight.notifications.sms import is_gsm7

    body = (
        "FloodSight code: 123456. "
        "Enter it to confirm your flood alert subscription. "
        "Not you? Ignore this message."
    )
    assert len(body) <= 160
    assert is_gsm7(body)


# ---------------------------------------------------------------------------
# OTP helpers
# ---------------------------------------------------------------------------

def test_otp_hash_and_flag(monkeypatch):
    from api.otp import hash_code as _hash_code
    from api.otp import otp_required as _otp_required

    h1 = _hash_code("123456", "+2348012345678")
    h2 = _hash_code("123456", "+2348012345678")
    h3 = _hash_code("654321", "+2348012345678")
    h4 = _hash_code("123456", "+2348099999999")
    assert h1 == h2
    assert h1 != h3 and h1 != h4          # code and phone both bind the hash
    assert len(h1) == 64                   # sha256 hex

    monkeypatch.delenv("REQUIRE_OTP", raising=False)
    assert _otp_required() is False
    monkeypatch.setenv("REQUIRE_OTP", "true")
    assert _otp_required() is True
    monkeypatch.setenv("REQUIRE_OTP", "0")
    assert _otp_required() is False


# ---------------------------------------------------------------------------
# Coastal summariser (pure — no network)
# ---------------------------------------------------------------------------

def test_coastal_summarise_advisory():
    from floodsight.forecast.marine import COASTAL_ADVISORY_M, summarize_sea_level

    times = ["2026-07-05T00:00", "2026-07-05T01:00", "2026-07-05T02:00"]
    quiet = summarize_sea_level(times, [0.2, 0.4, 0.3])
    assert quiet["advisory"] is False
    assert quiet["max_sea_level_m"] == 0.4
    assert quiet["peak_time"] == "2026-07-05T01:00"

    surge = summarize_sea_level(times, [0.2, COASTAL_ADVISORY_M + 0.2, None])
    assert surge["advisory"] is True
    assert surge["current_sea_level_m"] == 0.2


def test_coastal_summarise_empty_raises():
    from floodsight.forecast.marine import summarize_sea_level

    with pytest.raises(RuntimeError):
        summarize_sea_level(["2026-07-05T00:00"], [None])


# ---------------------------------------------------------------------------
# Morning briefing — coastal advisory line
# ---------------------------------------------------------------------------

def test_briefing_includes_coastal_line():
    import importlib.util
    from pathlib import Path

    spec = importlib.util.spec_from_file_location(
        "send_morning_briefing",
        Path(__file__).resolve().parent.parent / "scripts" / "send_morning_briefing.py",
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    summary = {
        "highest_alert": "No Alert",
        "alert_counts": {"Warning": 0, "Watch": 0, "No Alert": 100},
        "forecast": {"rain_24h_mm": 4.0, "rain_72h_mm": 9.0},
        "coastal": {"advisory": True, "max_sea_level_m": 1.15},
    }
    msg = mod.format_message(summary)
    assert "HIGH TIDE" in msg

    summary["coastal"] = None
    assert "HIGH TIDE" not in mod.format_message(summary)


if __name__ == "__main__":
    import sys

    sys.exit(pytest.main([__file__, "-v"]))
