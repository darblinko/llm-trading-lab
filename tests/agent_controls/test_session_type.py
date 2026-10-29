"""Tests for session-type classification and parameter overrides."""

import pytest

from agent_controls.session_type import (
    SessionType,
    SessionTypeParams,
    classify_session,
    get_params,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _classify(**overrides) -> SessionTypeParams:
    """Call classify_session with sensible defaults, overriding as needed."""
    defaults = dict(
        thesis_bias="bull",
        thesis_confidence="medium",
        thesis_state="intact",
        regime="bull_trend",
        mtf_aligned=True,
        session_trend_direction="bull",
        has_high_impact_events=False,
        slope_15m=0.3,
    )
    defaults.update(overrides)
    return classify_session(**defaults)


# ---------------------------------------------------------------------------
# Parameter value sanity checks
# ---------------------------------------------------------------------------


class TestParamValues:
    def test_trend_day_params(self):
        p = get_params(SessionType.TREND_DAY)
        assert p.max_hold_minutes == 120.0
        assert p.take_profit_reduce_pct == 1.50
        assert p.take_profit_close_pct == 3.00
        assert p.entry_gate == 70
        assert p.reentry_gate == 60
        assert p.checkin_interval_ticks == 5

    def test_breakout_day_params(self):
        p = get_params(SessionType.BREAKOUT_DAY)
        assert p.max_hold_minutes == 60.0
        assert p.take_profit_reduce_pct == 1.00
        assert p.entry_gate == 70
        assert p.reentry_gate == 65
        assert p.checkin_interval_ticks == 5

    def test_range_day_params(self):
        p = get_params(SessionType.RANGE_DAY)
        assert p.max_hold_minutes == 25.0
        assert p.take_profit_reduce_pct == 0.50
        assert p.entry_gate == 80
        assert p.reentry_gate == 80
        assert p.checkin_interval_ticks == 5

    def test_event_day_params(self):
        p = get_params(SessionType.EVENT_DAY)
        assert p.max_hold_minutes == 15.0
        assert p.take_profit_reduce_pct == 0.40
        assert p.entry_gate == 85
        assert p.reentry_gate == 85
        assert p.checkin_interval_ticks == 1

    def test_params_are_frozen(self):
        p = get_params(SessionType.TREND_DAY)
        with pytest.raises(AttributeError):
            p.entry_gate = 99  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Classification logic
# ---------------------------------------------------------------------------


class TestClassification:
    def test_event_day_overrides_all(self):
        """High-impact events force EVENT_DAY even with perfect trend signals."""
        result = _classify(
            thesis_confidence="high",
            regime="strong_bull_trend",
            mtf_aligned=True,
            slope_15m=0.5,
            has_high_impact_events=True,
        )
        assert result.session_type == SessionType.EVENT_DAY

    def test_trend_day_full_alignment(self):
        """All criteria met -> TREND_DAY."""
        result = _classify(
            thesis_confidence="high",
            regime="strong_bull_trend",
            mtf_aligned=True,
            slope_15m=0.4,
        )
        assert result.session_type == SessionType.TREND_DAY

    def test_trend_day_medium_confidence(self):
        """Medium confidence is sufficient for TREND_DAY."""
        result = _classify(thesis_confidence="medium")
        assert result.session_type == SessionType.TREND_DAY

    def test_trend_day_bear(self):
        """Bear thesis + bear regime + MTF = TREND_DAY."""
        result = _classify(
            thesis_bias="bear",
            regime="strong_bear_trend",
            session_trend_direction="bear",
        )
        assert result.session_type == SessionType.TREND_DAY

    def test_breakout_day_no_mtf(self):
        """Trending regime + intact thesis but MTF not aligned -> BREAKOUT_DAY."""
        result = _classify(mtf_aligned=False)
        assert result.session_type == SessionType.BREAKOUT_DAY

    def test_breakout_day_weak_slope(self):
        """Slope too weak for TREND_DAY -> BREAKOUT_DAY."""
        result = _classify(slope_15m=0.1)
        assert result.session_type == SessionType.BREAKOUT_DAY

    def test_breakout_day_none_slope(self):
        """None slope (insufficient bars) -> BREAKOUT_DAY."""
        result = _classify(slope_15m=None)
        assert result.session_type == SessionType.BREAKOUT_DAY

    def test_range_day_neutral_thesis(self):
        """Neutral thesis -> RANGE_DAY regardless of regime."""
        result = _classify(thesis_bias="neutral")
        assert result.session_type == SessionType.RANGE_DAY

    def test_breakout_day_low_confidence(self):
        """Low confidence with trending regime -> BREAKOUT_DAY (not TREND)."""
        result = _classify(thesis_confidence="low")
        assert result.session_type == SessionType.BREAKOUT_DAY

    def test_range_day_low_confidence_neutral_regime(self):
        """Low confidence + neutral regime -> RANGE_DAY."""
        result = _classify(thesis_confidence="low", regime="neutral")
        assert result.session_type == SessionType.RANGE_DAY

    def test_range_day_thesis_weakened(self):
        """Weakened thesis -> RANGE_DAY even with strong regime."""
        result = _classify(
            thesis_state="weakened",
            regime="strong_bull_trend",
        )
        assert result.session_type == SessionType.RANGE_DAY

    def test_range_day_thesis_invalidated(self):
        """Invalidated thesis -> RANGE_DAY."""
        result = _classify(thesis_state="invalidated")
        assert result.session_type == SessionType.RANGE_DAY

    def test_range_day_neutral_regime(self):
        """Neutral regime -> RANGE_DAY even with bullish thesis."""
        result = _classify(regime="neutral")
        assert result.session_type == SessionType.RANGE_DAY


# ---------------------------------------------------------------------------
# Transition scenarios
# ---------------------------------------------------------------------------


class TestTransitions:
    def test_thesis_weakens_trend_to_range(self):
        """When thesis weakens mid-session, reclassify from TREND to RANGE."""
        before = _classify(thesis_state="intact")
        assert before.session_type == SessionType.TREND_DAY

        after = _classify(thesis_state="weakened")
        assert after.session_type == SessionType.RANGE_DAY
        assert after.max_hold_minutes == 25.0

    def test_event_appears_overrides_trend(self):
        """When a high-impact event is imminent, override TREND to EVENT."""
        before = _classify(has_high_impact_events=False)
        assert before.session_type == SessionType.TREND_DAY

        after = _classify(has_high_impact_events=True)
        assert after.session_type == SessionType.EVENT_DAY

    def test_mtf_confirms_breakout_to_trend(self):
        """When MTF aligns, upgrade from BREAKOUT to TREND."""
        before = _classify(mtf_aligned=False, slope_15m=0.3)
        assert before.session_type == SessionType.BREAKOUT_DAY

        after = _classify(mtf_aligned=True, slope_15m=0.3)
        assert after.session_type == SessionType.TREND_DAY
