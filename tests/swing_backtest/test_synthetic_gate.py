from datetime import date

import numpy as np

from swing_backtest.demo import format_verdict, main, run
from swing_backtest.synthetic import (
    Bars,
    BracketRules,
    business_days,
    random_walk_bars,
    simulate_long,
)
from swing_backtest.trades import ExitReason


def _flat_bars(closes: list[float], highs: list[float], lows: list[float]) -> Bars:
    dates = business_days(date(2020, 1, 6), len(closes))
    close = np.array(closes, dtype=float)
    open_ = np.concatenate(([close[0]], close[:-1]))
    return Bars("TEST", dates, open_, np.array(highs), np.array(lows), close)


def test_business_days_skip_weekends():
    days = business_days(date(2020, 1, 3), 3)
    assert days == (date(2020, 1, 3), date(2020, 1, 6), date(2020, 1, 7))


def test_random_walk_bars_are_consistent():
    bars = random_walk_bars("X", business_days(date(2020, 1, 6), 50), np.random.default_rng(1))
    assert np.all(bars.high >= np.maximum(bars.open, bars.close))
    assert np.all(bars.low <= np.minimum(bars.open, bars.close))


def test_simulate_long_hits_target():
    bars = _flat_bars([100, 101, 107], [100, 101, 107], [100, 100, 106])
    result = simulate_long(bars, 0, BracketRules(max_hold_bars=2), "f", "c1")
    assert result.exit_reason is ExitReason.TARGET
    assert abs(result.r_multiple - 2.0) < 1e-9


def test_simulate_long_stop_wins_when_both_levels_touched():
    bars = _flat_bars([100, 100, 100], [100, 110, 100], [100, 90, 100])
    result = simulate_long(bars, 0, BracketRules(max_hold_bars=2), "f", "c1")
    assert result.exit_reason is ExitReason.STOP
    assert result.r_multiple <= -1.0


def test_simulate_long_open_gap_through_target_exits_at_the_open():
    # Entry 100, stop 97, target 106. The next bar opens at 110, then falls to 96.
    bars = Bars(
        "TEST",
        business_days(date(2020, 1, 6), 2),
        np.array([100.0, 110.0]),
        np.array([100.0, 111.0]),
        np.array([100.0, 96.0]),
        np.array([100.0, 96.5]),
    )
    result = simulate_long(bars, 0, BracketRules(max_hold_bars=1), "f", "c1")
    assert result.exit_reason is ExitReason.TARGET
    assert result.exit_price == 110.0


def test_simulate_long_open_gap_through_stop_exits_at_the_open():
    bars = Bars(
        "TEST",
        business_days(date(2020, 1, 6), 2),
        np.array([100.0, 95.0]),
        np.array([100.0, 107.0]),
        np.array([100.0, 94.0]),
        np.array([100.0, 106.5]),
    )
    result = simulate_long(bars, 0, BracketRules(max_hold_bars=1), "f", "c1")
    assert result.exit_reason is ExitReason.STOP
    assert result.exit_price == 95.0


def test_simulate_long_time_exit_and_short_history():
    bars = _flat_bars([100, 100.5, 101], [100, 101, 101], [100, 99.5, 100])
    result = simulate_long(bars, 0, BracketRules(max_hold_bars=2), "f", "c1")
    assert result.exit_reason is ExitReason.TIME
    assert simulate_long(bars, 1, BracketRules(max_hold_bars=2), "f", "c2") is None


def test_gate_fails_random_entries_and_passes_peeking_entries():
    verdicts = {v.family: v for v in run(seed=0, n_entries=600)}
    assert not verdicts["random"].passed
    assert not next(c for c in verdicts["random"].checks if c.name == "expectancy").passed
    assert verdicts["peeking"].passed


def test_demo_main_prints_both_families(capsys):
    assert main(["--entries", "300"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("random: FAIL")
    assert "peeking:" in out
    assert format_verdict(run(0, 300)[0]).splitlines()[0].startswith("random")
