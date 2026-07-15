"""
Tests for the FloodSight Health Intelligence Layer.

Run: pytest tests/test_health.py -v

All tests use mocks so they run without Supabase, Africa's Talking,
or Open-Meteo credentials. Add --log-cli-level=INFO to see engine logs.
"""

from __future__ import annotations

import math
from datetime import date
from unittest.mock import MagicMock, patch

import pytest


# ===========================================================================
# Fixtures
# ===========================================================================

def _make_geojson(lga: str, level: str, score: float, n_cells: int = 50) -> dict:
    """Build a minimal GeoJSON FeatureCollection with n_cells identical features."""
    return {
        "type": "FeatureCollection",
        "features": [
            {
                "type":       "Feature",
                "properties": {"lga_name": lga, "hazard_score": score},
                "geometry":   None,
            }
            for _ in range(n_cells)
        ],
    }


def _alert_levels(level: str, n_cells: int = 50) -> list[str]:
    return [level] * n_cells


# ===========================================================================
# engine.py — biological model unit tests
# ===========================================================================

class TestBreedingLag:
    def test_30c_returns_10_days(self):
        from floodsight.health.engine import _breeding_lag
        assert _breeding_lag(30.0) == 10

    def test_28c_returns_12_days(self):
        from floodsight.health.engine import _breeding_lag
        assert _breeding_lag(28.0) == 12

    def test_outside_range_returns_default(self):
        from floodsight.health.engine import _breeding_lag
        assert _breeding_lag(10.0) == 11   # below 26 °C → default
        assert _breeding_lag(40.0) == 11   # above 32 °C → default

    def test_float_rounds_correctly(self):
        from floodsight.health.engine import _breeding_lag
        # 29.6 rounds to 30 → 10 days
        assert _breeding_lag(29.6) == 10
        # 29.4 rounds to 29 → 11 days
        assert _breeding_lag(29.4) == 11


class TestOutbreakProbability:
    def test_high_inundation_high_susceptibility_gives_high_prob(self):
        from floodsight.health.engine import _outbreak_probability
        p = _outbreak_probability(5.0, 0.80, 30.0)
        assert p >= 0.55, f"Expected >= 0.55, got {p}"

    def test_small_flood_ranks_below_large_flood(self):
        # The engine is an UNCALIBRATED rule-based prior: we test the property
        # it actually claims - monotonic RANKING (a small flood must score
        # below a large one, same susceptibility/temperature) - not an
        # absolute tier, which would imply a calibration we explicitly disclaim.
        from floodsight.health.engine import _risk_prior
        small = _risk_prior(0.3, 0.60, 28.0)
        large = _risk_prior(5.0, 0.60, 28.0)
        assert small < large, f"small={small} should rank below large={large}"

    def test_score_carries_uncalibrated_provenance(self):
        from floodsight.health.engine import RISK_MODEL_CALIBRATION, RISK_MODEL_TYPE
        assert RISK_MODEL_TYPE == "rule_based_prior"
        assert "uncalibrated" in RISK_MODEL_CALIBRATION

    def test_probability_always_in_unit_interval(self):
        from floodsight.health.engine import _outbreak_probability
        for area in [0.0, 0.1, 0.5, 1, 5, 10, 100, 1000]:
            p = _outbreak_probability(area, 1.0, 32.0)
            assert 0.0 <= p <= 1.0, f"Out of bounds for area={area}: {p}"

    def test_capped_at_10km2(self):
        """Probability should be same for 10 km² and 1000 km² (capped)."""
        from floodsight.health.engine import _outbreak_probability
        p10   = _outbreak_probability(10.0, 0.75, 30.0)
        p1000 = _outbreak_probability(1000.0, 0.75, 30.0)
        assert p10 == p1000, "Capping at 10 km² should make them equal"

    def test_temperature_factor_peaks_at_30c(self):
        """Probability at 30 °C should exceed 24 °C and 36 °C (same area/susceptibility)."""
        from floodsight.health.engine import _outbreak_probability
        p30 = _outbreak_probability(2.0, 0.70, 30.0)
        p24 = _outbreak_probability(2.0, 0.70, 24.0)
        p36 = _outbreak_probability(2.0, 0.70, 36.0)
        assert p30 > p24, f"30 °C ({p30}) should beat 24 °C ({p24})"
        assert p30 > p36, f"30 °C ({p30}) should beat 36 °C ({p36})"


class TestRiskTier:
    def test_low_tier(self):
        from floodsight.health.engine import _risk_tier
        assert _risk_tier(0.10) == "Low"
        assert _risk_tier(0.00) == "Low"

    def test_moderate_tier(self):
        from floodsight.health.engine import _risk_tier
        assert _risk_tier(0.30) == "Moderate"
        assert _risk_tier(0.49) == "Moderate"

    def test_high_tier(self):
        from floodsight.health.engine import _risk_tier
        assert _risk_tier(0.55) == "High"
        assert _risk_tier(0.74) == "High"

    def test_critical_tier(self):
        from floodsight.health.engine import _risk_tier
        assert _risk_tier(0.75) == "Critical"
        assert _risk_tier(0.99) == "Critical"


class TestScoreLgas:
    @patch("floodsight.health.engine._fetch_temperature", return_value=30.0)
    def test_watch_cells_scored(self, _mock):
        from floodsight.health.engine import score_lgas
        geojson = _make_geojson("Alimosho", "", 0.75, n_cells=50)
        levels  = _alert_levels("Watch", 50)
        results = score_lgas(geojson, levels)
        alimosho = [r for r in results if r["lga_name"] == "Alimosho"]
        assert alimosho, "Alimosho should be scored"

    @patch("floodsight.health.engine._fetch_temperature", return_value=30.0)
    def test_warning_cells_scored(self, _mock):
        from floodsight.health.engine import score_lgas
        geojson = _make_geojson("Kosofe", "", 0.80, n_cells=50)
        levels  = _alert_levels("Warning", 50)
        results = score_lgas(geojson, levels)
        assert any(r["lga_name"] == "Kosofe" for r in results)

    @patch("floodsight.health.engine._fetch_temperature", return_value=30.0)
    def test_no_alert_cells_not_scored(self, _mock):
        from floodsight.health.engine import score_lgas
        geojson = _make_geojson("Surulere", "", 0.80, n_cells=100)
        levels  = _alert_levels("No Alert", 100)
        results = score_lgas(geojson, levels)
        assert not any(r["lga_name"] == "Surulere" for r in results)

    @patch("floodsight.health.engine._fetch_temperature", return_value=30.0)
    def test_below_min_inundation_not_scored(self, _mock):
        """10 cells × 0.04 km² = 0.40 km² < MIN_INUNDATION_KM2 (0.5)."""
        from floodsight.health.engine import score_lgas
        geojson = _make_geojson("Eti-Osa", "", 0.80, n_cells=10)
        levels  = _alert_levels("Warning", 10)
        results = score_lgas(geojson, levels)
        assert not any(r["lga_name"] == "Eti-Osa" for r in results)

    @patch("floodsight.health.engine._fetch_temperature", return_value=30.0)
    def test_results_sorted_by_probability_desc(self, _mock):
        from floodsight.health.engine import score_lgas
        features = []
        levels   = []
        for lga, n in [("Alimosho", 100), ("Kosofe", 15)]:
            features += [
                {
                    "type": "Feature",
                    "properties": {"lga_name": lga, "hazard_score": 0.75},
                    "geometry": None,
                }
                for _ in range(n)
            ]
            levels += ["Warning"] * n
        results = score_lgas({"type": "FeatureCollection", "features": features}, levels)
        probs = [r["outbreak_probability"] for r in results]
        assert probs == sorted(probs, reverse=True), "Results must be sorted descending"

    @patch("floodsight.health.engine._fetch_temperature", return_value=30.0)
    def test_outbreak_window_dates_correct(self, _mock):
        """Window should start breeding_lag_days from today."""
        from floodsight.health.engine import score_lgas
        from datetime import timedelta
        geojson = _make_geojson("Alimosho", "", 0.75, n_cells=50)
        levels  = _alert_levels("Warning", 50)
        results = score_lgas(geojson, levels)
        r = results[0]
        lag      = r["breeding_lag_days"]
        expected = (date.today() + timedelta(days=lag)).isoformat()
        assert r["outbreak_window_start"] == expected

    @patch("floodsight.health.engine._fetch_temperature", return_value=30.0)
    def test_mismatched_lengths_does_not_crash(self, _mock):
        """score_lgas should handle len(features) != len(alert_levels) gracefully."""
        from floodsight.health.engine import score_lgas
        geojson = _make_geojson("Alimosho", "", 0.75, n_cells=50)
        levels  = _alert_levels("Warning", 30)   # shorter
        # Should not raise
        results = score_lgas(geojson, levels)
        assert isinstance(results, list)

    @patch("floodsight.health.engine._fetch_temperature", return_value=30.0)
    def test_flood_event_id_propagated(self, _mock):
        from floodsight.health.engine import score_lgas
        geojson = _make_geojson("Alimosho", "", 0.75, n_cells=50)
        levels  = _alert_levels("Warning", 50)
        results = score_lgas(geojson, levels, flood_event_id="2026-07-14")
        assert results[0]["flood_event_id"] == "2026-07-14"


class TestFetchTemperature:
    def test_returns_float(self):
        """Temperature function should always return a float even on failure."""
        from floodsight.health.engine import _fetch_temperature
        with patch("floodsight.health.engine.requests.get") as mock_get:
            mock_get.side_effect = ConnectionError("network down")
            t = _fetch_temperature()
        assert isinstance(t, float)
        assert t == 28.0   # fallback default


# ===========================================================================
# chew_alerts.py — message composition
# ===========================================================================

class TestComposeMessage:
    def test_message_within_160_chars(self):
        from floodsight.health.chew_alerts import compose_message
        msg = compose_message(
            lga_name="Ajeromi-Ifelodun",
            risk_tier="Critical",
            outbreak_window_start="2026-07-25",
            outbreak_window_end="2026-08-01",
            inundation_km2=3.5,
        )
        assert len(msg) <= 160, f"Message {len(msg)} chars — exceeds 160: {msg!r}"

    def test_message_contains_lga(self):
        from floodsight.health.chew_alerts import compose_message
        msg = compose_message("Alimosho", "High", "2026-07-25", "2026-08-01", 1.2)
        assert "Alimosho" in msg

    def test_critical_includes_urgent(self):
        from floodsight.health.chew_alerts import compose_message
        msg = compose_message("Kosofe", "Critical", "2026-07-25", "2026-08-01", 5.0)
        assert "URGENT" in msg

    def test_moderate_does_not_include_urgent(self):
        from floodsight.health.chew_alerts import compose_message
        msg = compose_message("Kosofe", "Moderate", "2026-07-25", "2026-08-01", 0.8)
        assert "URGENT" not in msg

    def test_all_tiers_generate_messages(self):
        from floodsight.health.chew_alerts import compose_message
        for tier in ("Moderate", "High", "Critical"):
            msg = compose_message("Alimosho", tier, "2026-07-25", "2026-08-01", 1.0)
            assert msg
            assert len(msg) <= 160

    def test_low_tier_raises(self):
        from floodsight.health.chew_alerts import compose_message
        with pytest.raises(ValueError, match="Low-tier"):
            compose_message("Alimosho", "Low", "2026-07-25", "2026-08-01", 0.3)

    def test_message_contains_reply_instruction(self):
        from floodsight.health.chew_alerts import compose_message
        msg = compose_message("Kosofe", "High", "2026-07-25", "2026-08-01", 2.0)
        assert "CONFIRM" in msg

    def test_idempotency_key_deterministic(self):
        from floodsight.health.chew_alerts import _idem_key
        k1 = _idem_key("Alimosho", "+2348012345678", "2026-07-14")
        k2 = _idem_key("Alimosho", "+2348012345678", "2026-07-14")
        assert k1 == k2

    def test_idempotency_key_different_lga(self):
        from floodsight.health.chew_alerts import _idem_key
        k1 = _idem_key("Alimosho", "+2348012345678", "2026-07-14")
        k2 = _idem_key("Kosofe",   "+2348012345678", "2026-07-14")
        assert k1 != k2

    def test_idempotency_key_different_date(self):
        from floodsight.health.chew_alerts import _idem_key
        k1 = _idem_key("Alimosho", "+2348012345678", "2026-07-14")
        k2 = _idem_key("Alimosho", "+2348012345678", "2026-07-15")
        assert k1 != k2


# ===========================================================================
# API router — response parsing
# ===========================================================================

class TestChewResponseParsing:
    """Test the CHEW reply parser in the health router (inline logic)."""

    def _parse(self, text: str):
        """Replicate the parsing logic from api/routers/health.py."""
        normalized     = text.strip().upper()
        parsed_action  = "UNKNOWN"
        cases_reported = None
        if normalized.startswith("CONFIRM"):
            parsed_action = "CONFIRM"
        elif normalized.startswith("REPORT"):
            parsed_action = "REPORT"
            parts = normalized.split()
            if len(parts) >= 2 and parts[1].isdigit():
                cases_reported = int(parts[1])
        elif normalized.startswith("HELP"):
            parsed_action = "HELP"
        return parsed_action, cases_reported

    def test_confirm(self):
        action, cases = self._parse("CONFIRM")
        assert action == "CONFIRM"
        assert cases is None

    def test_confirm_with_trailing_text(self):
        action, cases = self._parse("confirm I have distributed nets")
        assert action == "CONFIRM"

    def test_report_with_count(self):
        action, cases = self._parse("REPORT 12")
        assert action == "REPORT"
        assert cases == 12

    def test_report_without_count(self):
        action, cases = self._parse("REPORT")
        assert action == "REPORT"
        assert cases is None

    def test_help(self):
        action, cases = self._parse("HELP")
        assert action == "HELP"

    def test_unknown(self):
        action, cases = self._parse("random text")
        assert action == "UNKNOWN"

    def test_case_insensitive(self):
        action, _ = self._parse("confirm")
        assert action == "CONFIRM"
        action, _ = self._parse("Report 5")
        assert action == "REPORT"


# ===========================================================================
# config.py — health constants present
# ===========================================================================

class TestHealthConfig:
    def test_pilot_lat_lon_in_config(self):
        from floodsight.config import PILOT_LAT, PILOT_LON
        assert abs(PILOT_LAT - 6.520) < 0.01
        assert abs(PILOT_LON - 3.370) < 0.01

    def test_health_pilot_lgas_count(self):
        from floodsight.config import HEALTH_PILOT_LGAS
        assert len(HEALTH_PILOT_LGAS) == 5

    def test_health_control_lgas_count(self):
        from floodsight.config import HEALTH_CONTROL_LGAS
        assert len(HEALTH_CONTROL_LGAS) == 5

    def test_pilot_and_control_disjoint(self):
        from floodsight.config import HEALTH_PILOT_LGAS, HEALTH_CONTROL_LGAS
        overlap = HEALTH_PILOT_LGAS & HEALTH_CONTROL_LGAS
        assert not overlap, f"Pilot and control LGAs overlap: {overlap}"

    def test_anopheles_dev_days_present(self):
        from floodsight.config import ANOPHELES_DEV_DAYS
        assert 26 in ANOPHELES_DEV_DAYS
        assert 32 in ANOPHELES_DEV_DAYS
        # Values should be monotonically decreasing (hotter = faster development)
        temps = sorted(ANOPHELES_DEV_DAYS.keys())
        days  = [ANOPHELES_DEV_DAYS[t] for t in temps]
        assert days == sorted(days, reverse=True), "Days should decrease as temperature rises"

    def test_health_min_inundation_positive(self):
        from floodsight.config import HEALTH_MIN_INUNDATION_KM2
        assert HEALTH_MIN_INUNDATION_KM2 > 0


# ===========================================================================
# mel.py — event type validation
# ===========================================================================

class TestMelValidation:
    def test_invalid_event_type_raises(self):
        from floodsight.health.mel import record_mel_event
        with pytest.raises(ValueError, match="Invalid event_type"):
            # Bypass Supabase call — ValueError fires before DB access
            record_mel_event(
                lga_name="Alimosho",
                event_type="INVALID_TYPE",
                event_date=date.today(),
            )

    def test_valid_event_types_do_not_raise_on_type_check(self):
        """Check all valid event types pass the validation gate (mock DB)."""
        from floodsight.health.mel import VALID_EVENT_TYPES, record_mel_event
        with patch("floodsight.db.supabase_client.log_mel_event", return_value={"id": 1}):
            for et in VALID_EVENT_TYPES:
                result = record_mel_event(
                    lga_name="Kosofe",
                    event_type=et,
                    event_date=date.today(),
                    quantity=100,
                    unit="units",
                )
                assert result is not None


    def test_operational_and_entomology_event_types_present(self):
        # The rework adds operational + entomology verification events used by
        # the PRIMARY PoC outcomes (alert-to-action, Anopheles confirmation).
        from floodsight.health.mel import VALID_EVENT_TYPES
        for et in ("ALERT_ACKNOWLEDGED", "LARVAL_SURVEY_CONDUCTED",
                   "ANOPHELES_CONFIRMED", "CULEX_ONLY", "LARVAL_SOURCE_MANAGEMENT"):
            assert et in VALID_EVENT_TYPES, f"{et} missing from VALID_EVENT_TYPES"


class TestOperationalKpis:
    def test_kpis_are_none_safe_when_empty(self):
        # Before enrolment there is no data; get_operational_kpis must return
        # a well-formed dict (0 / None), never raise, so the dashboard renders.
        from unittest.mock import MagicMock, patch as _patch
        from floodsight.health import mel as mel_mod

        empty = MagicMock()
        empty.table.return_value.select.return_value.execute.return_value.data = []
        with _patch("floodsight.db.supabase_client._get_client", return_value=empty):
            k = mel_mod.get_operational_kpis()
        assert k["alerts_sent"] == 0
        assert k["O1_acknowledgement_rate"] is None
        assert "O4_anopheles_confirmation_rate" in k
