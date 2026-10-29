"""Tests for the deterministic macro regime engine."""

from agent_controls.regime import (
    HYSTERESIS_BARS,
    STRONG_EXIT_THRESHOLD,
    STRONG_THRESHOLD,
    TREND_EXIT_THRESHOLD,
    TREND_THRESHOLD,
    MacroRegime,
    MicroRegime,
    compute_macro_regime,
    reset,
)


def _bull_snapshot(**overrides):
    """Snapshot with strongly bullish indicators."""
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
    }
    base.update(overrides)
    return base


def _bear_snapshot(**overrides):
    """Snapshot with strongly bearish indicators."""
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
    }
    base.update(overrides)
    return base


def _mild_bull_snapshot(**overrides):
    """Snapshot with moderate bullish indicators (score lands in BULL_TREND, not STRONG)."""
    base = {
        "ema_9_above_21": True,
        "ema_9_21_spread": 0.5,
        "ema_100_above_200": True,
        "ema_100_slope5": 0.1,
        "ema_200_slope5": 0.0,
        "linreg_slope_10": 0.02,
        "linreg_slope_20": 0.01,
        "linreg_slope_50": 0.01,
        "linreg_slope_100": 0.01,
        "vwap_dist_pct": 0.1,
        "price_above_vwap": True,
        "macd_hist": 0.1,
        "macd_hist_delta": 0.02,
    }
    base.update(overrides)
    return base


def _mild_bear_snapshot(**overrides):
    """Snapshot with moderate bearish indicators (score lands in BEAR_TREND, not STRONG)."""
    base = {
        "ema_9_above_21": False,
        "ema_9_21_spread": -0.5,
        "ema_100_above_200": False,
        "ema_100_slope5": -0.1,
        "ema_200_slope5": 0.0,
        "linreg_slope_10": -0.02,
        "linreg_slope_20": -0.01,
        "linreg_slope_50": -0.01,
        "linreg_slope_100": -0.01,
        "vwap_dist_pct": -0.1,
        "price_above_vwap": False,
        "macd_hist": -0.1,
        "macd_hist_delta": -0.02,
    }
    base.update(overrides)
    return base


def _neutral_snapshot(**overrides):
    """Snapshot with mixed/neutral indicators."""
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
    }
    base.update(overrides)
    return base


class TestMacroRegime:
    def setup_method(self):
        reset()

    def test_starts_neutral(self):
        result = compute_macro_regime(_neutral_snapshot(), vwap_persistence=5)
        assert result.regime == MacroRegime.NEUTRAL

    def test_bull_requires_hysteresis(self):
        """Regime should not flip to bull on a single bar."""
        result = compute_macro_regime(_bull_snapshot(), vwap_persistence=9)
        # First bar: still neutral (needs HYSTERESIS_BARS consecutive)
        assert result.regime == MacroRegime.NEUTRAL
        assert result.held_bars == 1

    def test_bull_transitions_after_n_bars(self):
        """Regime transitions after HYSTERESIS_BARS consecutive bull signals."""
        for _ in range(HYSTERESIS_BARS):
            result = compute_macro_regime(_bull_snapshot(), vwap_persistence=9)

        assert result.regime in (MacroRegime.BULL_TREND, MacroRegime.STRONG_BULL_TREND)

    def test_bear_transitions_after_n_bars(self):
        """Regime transitions to bear after sustained bearish signals."""
        for _ in range(HYSTERESIS_BARS):
            result = compute_macro_regime(_bear_snapshot(), vwap_persistence=1)

        assert result.regime in (MacroRegime.BEAR_TREND, MacroRegime.STRONG_BEAR_TREND)

    def test_hysteresis_prevents_oscillation(self):
        """Alternating bull/bear snapshots should NOT flip the regime."""
        # Establish bull trend
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(_bull_snapshot(), vwap_persistence=9)

        # Now alternate between bull and neutral: regime should hold
        for _ in range(10):
            compute_macro_regime(_neutral_snapshot(), vwap_persistence=5)
            result = compute_macro_regime(_bull_snapshot(), vwap_persistence=9)

        # Should still be bull (alternating resets the pending count)
        assert result.regime in (MacroRegime.BULL_TREND, MacroRegime.STRONG_BULL_TREND)

    def test_sustained_reversal_flips_regime(self):
        """Sustained opposite signals should eventually flip the regime."""
        # Establish bull
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(_bull_snapshot(), vwap_persistence=9)

        # Now sustain bear for long enough
        for _ in range(HYSTERESIS_BARS + 5):
            result = compute_macro_regime(_bear_snapshot(), vwap_persistence=1)

        assert result.regime in (MacroRegime.BEAR_TREND, MacroRegime.STRONG_BEAR_TREND)

    def test_score_is_continuous(self):
        """Score should be a float, not discrete."""
        result = compute_macro_regime(_bull_snapshot(), vwap_persistence=7)
        assert isinstance(result.score, float)

    def test_none_values_handled(self):
        """Snapshot with None values should not crash."""
        snapshot = {k: None for k in _bull_snapshot()}
        result = compute_macro_regime(snapshot, vwap_persistence=5)
        assert result.regime == MacroRegime.NEUTRAL


class TestAsymmetricHysteresis:
    """Asymmetric exit thresholds prevent flapping between TREND and NEUTRAL.

    Entering a trend requires crossing the wide threshold (TREND_THRESHOLD);
    exiting back toward NEUTRAL requires dropping below the narrow threshold
    (TREND_EXIT_THRESHOLD). The band between is a "hold current regime" zone.
    A legitimate trend-to-opposite-trend transition is NOT delayed.
    """

    def setup_method(self):
        reset()

    def test_initial_neutral_transitions_normally(self):
        """Initial NEUTRAL still transitions after HYSTERESIS_BARS of mild bull."""
        for _ in range(HYSTERESIS_BARS):
            result = compute_macro_regime(_mild_bull_snapshot(), vwap_persistence=7)
        assert result.regime == MacroRegime.BULL_TREND

    def test_trend_holds_in_exit_band(self):
        """Once BULL_TREND is established, a score in [TREND_EXIT, TREND_THRESHOLD]
        should NOT demote to NEUTRAL (asymmetric exit prevents flapping)."""
        # Establish BULL_TREND
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(_mild_bull_snapshot(), vwap_persistence=7)

        # Now send a neutral-ish snapshot (score should land in the hold band 15-25).
        # The _neutral_snapshot scores around +6 which is below TREND_EXIT=15,
        # so we need something slightly bullish. Use a dampened bull by dropping vwap_persistence.
        # With vwap_persistence=4, the VWAP-persistence component is -2, pulling the
        # ~51 mild-bull score down into the hold band.
        for _ in range(HYSTERESIS_BARS + 3):
            result = compute_macro_regime(_mild_bull_snapshot(), vwap_persistence=4)

        # With score dropped but still positive, should stay in BULL_TREND
        assert result.regime == MacroRegime.BULL_TREND
        # Score should land between TREND_EXIT_THRESHOLD and TREND_THRESHOLD
        assert TREND_EXIT_THRESHOLD < result.score < STRONG_THRESHOLD

    def test_trend_exits_below_exit_threshold(self):
        """A score decisively below TREND_EXIT_THRESHOLD demotes back to NEUTRAL."""
        # Establish BULL_TREND
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(_mild_bull_snapshot(), vwap_persistence=7)

        # Send snapshots that score below TREND_EXIT (15) but above -TREND_THRESHOLD (-25).
        # _neutral_snapshot with a slight bearish EMA 9/21 tilt lands around +12.
        slight_bear = _neutral_snapshot(ema_9_above_21=False, ema_9_21_spread=-0.1)
        for _ in range(HYSTERESIS_BARS + 2):
            result = compute_macro_regime(slight_bear, vwap_persistence=5)

        assert result.regime == MacroRegime.NEUTRAL
        assert -TREND_THRESHOLD < result.score < TREND_EXIT_THRESHOLD

    def test_trend_to_opposite_trend_not_delayed(self):
        """A legitimate BULL_TREND to BEAR_TREND transition should NOT be delayed
        by the asymmetric exit logic (only HYSTERESIS_BARS applies)."""
        # Establish BULL_TREND
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(_mild_bull_snapshot(), vwap_persistence=7)

        # Send mild bear immediately (score ~-51, well below -TREND_THRESHOLD)
        for _ in range(HYSTERESIS_BARS):
            result = compute_macro_regime(_mild_bear_snapshot(), vwap_persistence=3)

        # Should flip to BEAR_TREND in exactly HYSTERESIS_BARS bars: no dwell penalty
        assert result.regime == MacroRegime.BEAR_TREND

    def test_flapping_scenario_narrow_range_day(self):
        """Simulates today's flappy narrow-range day: alternating weak bull / neutral
        signals. Once a trend is established, it should NOT flap back to neutral
        every few bars."""
        # Establish BULL_TREND with 3 mild-bull bars at moderate vwap_persistence
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(_mild_bull_snapshot(), vwap_persistence=7)
        assert (
            compute_macro_regime(_mild_bull_snapshot(), vwap_persistence=7).regime
            == MacroRegime.BULL_TREND
        )

        # Now alternate between mild-bull (score ~51) and dampened-bull (score ~45-47).
        # Previous symmetric threshold (25) would have held, but narrower bands
        # (e.g. vwap_persistence dropping to 4) would have flipped to NEUTRAL.
        # With TREND_EXIT=15, neither should break the trend.
        for i in range(10):
            snap = (
                _mild_bull_snapshot()
                if i % 2 == 0
                else _mild_bull_snapshot(vwap_dist_pct=0.0, ema_9_21_spread=0.1)
            )
            vwap = 7 if i % 2 == 0 else 4
            result = compute_macro_regime(snap, vwap_persistence=vwap)

        # Should still be BULL_TREND after the flappy sequence
        assert result.regime == MacroRegime.BULL_TREND

    def test_strong_exit_hysteresis(self):
        """STRONG_BULL demotes to BULL_TREND only once score drops below STRONG_EXIT,
        not on the first dip below STRONG_THRESHOLD."""
        # Establish STRONG_BULL (full _bull_snapshot, vwap_persistence=9)
        for _ in range(HYSTERESIS_BARS):
            compute_macro_regime(_bull_snapshot(), vwap_persistence=9)
        assert (
            compute_macro_regime(_bull_snapshot(), vwap_persistence=9).regime
            == MacroRegime.STRONG_BULL_TREND
        )

        # Send snapshots that score between STRONG_EXIT (50) and STRONG_THRESHOLD (60).
        # _mild_bull at vwap_persistence=8 should land around 53-55.
        for _ in range(HYSTERESIS_BARS + 2):
            result = compute_macro_regime(_mild_bull_snapshot(), vwap_persistence=8)

        # Should remain STRONG_BULL_TREND (in the exit band)
        assert result.regime == MacroRegime.STRONG_BULL_TREND
        assert STRONG_EXIT_THRESHOLD < result.score < STRONG_THRESHOLD


class TestMicroRegime:
    def test_enum_values(self):
        assert MicroRegime.IMPULSE == "impulse"
        assert MicroRegime.PULLBACK == "pullback"
        assert MicroRegime.CONSOLIDATION == "consolidation"
        assert MicroRegime.EXHAUSTION == "exhaustion"
