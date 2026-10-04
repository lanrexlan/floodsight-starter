"""
Two-tier coastal signal (calibrated October 2026).

The original single 0.9 m threshold was active on ~50 days a year, almost all
of them predictable equinox spring tides, and on each of those days it lifted
five coastal LGAs from No Alert to Watch on dry, calm weather. These tests pin
the replacement behaviour so it cannot regress silently:

  * a spring tide alone never raises an alert on a dry cell
  * a spring tide during rain escalates Watch -> Warning (tide-locking)
  * a genuine surge raises an alert on its own
"""

from floodsight.forecast.marine import (
    COASTAL_ADVISORY_M,
    COASTAL_HIGH_TIDE_M,
    COASTAL_SURGE_M,
    coastal_upgrade,
    summarize_sea_level,
)

TIMES = ["2026-03-10T00:00", "2026-03-10T06:00", "2026-03-10T12:00"]

# Highest daily max in the 2023-01-01 .. 2026-10-01 model record (1,354 days).
OBSERVED_MAX_2023_2026 = 1.15


# --- calibration invariants ------------------------------------------------

def test_surge_threshold_sits_above_the_astronomical_record():
    # If the surge tier could be reached by tide alone it would reintroduce
    # dry-day false alarms. It must stay above everything tide has produced.
    assert COASTAL_SURGE_M > OBSERVED_MAX_2023_2026


def test_tiers_are_ordered():
    assert COASTAL_HIGH_TIDE_M < COASTAL_SURGE_M


def test_legacy_name_points_at_surge_tier():
    assert COASTAL_ADVISORY_M == COASTAL_SURGE_M


# --- summariser ----------------------------------------------------------

def test_calm_sea_sets_no_tier():
    s = summarize_sea_level(TIMES, [0.3, 0.6, 0.5])
    assert s["advisory"] is False and s["high_tide"] is False and s["tier"] is None


def test_equinox_spring_tide_is_high_tide_not_surge():
    s = summarize_sea_level(TIMES, [0.4, OBSERVED_MAX_2023_2026, 0.7])
    assert s["advisory"] is False
    assert s["high_tide"] is True
    assert s["tier"] == "high_tide"


def test_surge_sets_both_flags():
    s = summarize_sea_level(TIMES, [0.5, COASTAL_SURGE_M + 0.05, None])
    assert s["advisory"] is True and s["high_tide"] is True and s["tier"] == "surge"


# --- upgrade semantics -----------------------------------------------------

HIGH_TIDE = {"advisory": False, "high_tide": True}
SURGE     = {"advisory": True,  "high_tide": True}
CALM      = {"advisory": False, "high_tide": False}


def test_high_tide_never_alerts_a_dry_cell():
    # The core fix: this is the old 33-50 false alarms a year.
    assert coastal_upgrade("No Alert", HIGH_TIDE) == "No Alert"


def test_high_tide_escalates_rain_watch():
    assert coastal_upgrade("Watch", HIGH_TIDE) == "Warning"


def test_surge_alerts_a_dry_cell():
    assert coastal_upgrade("No Alert", SURGE) == "Watch"
    assert coastal_upgrade("Watch", SURGE) == "Warning"


def test_warning_is_the_ceiling():
    for sig in (HIGH_TIDE, SURGE):
        assert coastal_upgrade("Warning", sig) == "Warning"


def test_no_signal_or_missing_data_leaves_level_unchanged():
    for level in ("No Alert", "Watch", "Warning"):
        assert coastal_upgrade(level, CALM) == level
        assert coastal_upgrade(level, None) == level
