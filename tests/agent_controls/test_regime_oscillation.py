"""Tests for regime oscillation detection and session trend."""

from agent_controls.regime import (
    HYSTERESIS_BARS,
    OSCILLATION_THRESHOLD,
    compute_macro_regime,
    get_regime_oscillation_count,
    get_session_trend,
    get_total_regime_changes,
    is_regime_oscillating,
    reset,
)


def _bull_snapshot(**overrides):
    base = {
        "ema_9_above_21": True,
        "ema_9_21_spread": 1.5,
        "ema_100_above_200": True,
        "ema_100_slope5": 0.5,
        "ema_200_slope5": 0.3,
        "linreg_slope_10": 0.08,
        "linreg_slope_20": 0.06,
        "linreg_slope_50": 0.04,
        "linreg_slope_100": 0.02,
        "vwap_dist_pct": 0.5,
        "price_above_vwap": True,
        "macd_hist": 0.3,
        "macd_hist_delta": 0.1,
        "price": 585.0,
    }
    base.update(overrides)
    return base


def _bear_snapshot(**overrides):
    base = {
        "ema_9_above_21": False,
        "ema_9_21_spread": -1.5,
        "ema_100_above_200": False,
        "ema_100_slope5": -0.5,
        "ema_200_slope5": -0.3,
        "linreg_slope_10": -0.08,
        "linreg_slope_20": -0.06,
        "linreg_slope_50": -0.04,
        "linreg_slope_100": -0.02,
        "vwap_dist_pct": -0.5,
        "price_above_vwap": False,
        "macd_hist": -0.3,
        "macd_hist_delta": -0.1,
        "price": 580.0,
    }
    base.update(overrides)
    return base


def _neutral_snapshot(**overrides):
    base = {
        "ema_9_above_21": True,
        "ema_9_21_spread": 0.1,
        "ema_100_above_200": True,
        "ema_100_slope5": 0.0,
        "linreg_slope_10": 0.01,
        "linreg_slope_20": -0.01,
        "linreg_slope_50": 0.0,
        "linreg_slope_100": 0.0,
        "vwap_dist_pct": 0.0,
        "price_above_vwap": True,
        "macd_hist": 0.01,
        "macd_hist_delta": 0.0,
        "price": 583.0,
    }
    base.update(overrides)
    return base


class TestRegimeOscillation:
    def setup_method(self):
        reset()

    def test_no_oscillation_initially(self):
        assert get_regime_oscillation_count() == 0
        assert not is_regime_oscillating()

    def test_single_transition_not_oscillating(self):
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(_bull_snapshot(), vwap_persistence=9)
        assert get_total_regime_changes() == 1
        assert not is_regime_oscillating()

    def test_oscillation_detected_after_many_transitions(self):
        # Force multiple regime transitions by alternating bull/bear for long enough
        for cycle in range(OSCILLATION_THRESHOLD + 1):
            snap = _bull_snapshot() if cycle % 2 == 0 else _bear_snapshot()
            vwap = 9 if cycle % 2 == 0 else 1
            for _ in range(HYSTERESIS_BARS + 1):
                compute_macro_regime(snap, vwap_persistence=vwap)

        assert get_total_regime_changes() >= OSCILLATION_THRESHOLD
        assert is_regime_oscillating()


class TestSessionTrend:
    def setup_method(self):
        reset()

    def test_no_trend_initially(self):
        trend = get_session_trend({"price": 580.0})
        assert trend.direction == "none"

    def test_bull_trend_detected(self):
        # First call sets session open
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(
                _bull_snapshot(price=580.0, price_above_vwap=True), vwap_persistence=9
            )

        # Simulate 15 bars above VWAP to exceed the 10-bar minimum
        for _ in range(15):
            compute_macro_regime(
                _bull_snapshot(price=590.0, price_above_vwap=True), vwap_persistence=9
            )

        # Price moved +10 from 580, ATR=10 -> 10 > 0.5*10 = 5, and most bars above VWAP
        trend = get_session_trend({"price": 590.0, "atr_14": 10.0})
        assert trend.direction == "bull"
        assert trend.move_from_open > 0

    def test_bear_trend_detected(self):
        # Open at 590, drop to 580
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(
                _bear_snapshot(price=590.0, price_above_vwap=False), vwap_persistence=1
            )

        for _ in range(15):
            compute_macro_regime(
                _bear_snapshot(price=580.0, price_above_vwap=False), vwap_persistence=1
            )

        trend = get_session_trend({"price": 580.0, "atr_14": 10.0})
        assert trend.direction == "bear"
        assert trend.move_from_open < 0

    def test_no_trend_when_move_too_small(self):
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(
                _neutral_snapshot(price=583.0, price_above_vwap=True), vwap_persistence=5
            )

        for _ in range(15):
            compute_macro_regime(
                _neutral_snapshot(price=584.0, price_above_vwap=True), vwap_persistence=5
            )

        # Only +1 move, ATR=10 -> 1 < 0.5*10 = 5
        trend = get_session_trend({"price": 584.0, "atr_14": 10.0})
        assert trend.direction == "none"
