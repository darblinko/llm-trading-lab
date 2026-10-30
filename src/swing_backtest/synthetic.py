"""Synthetic daily bars and a bracket-exit simulator for exercising the Stage A gate.

The bars are a geometric random walk. A family of random entries on them has no edge
by construction, so the gate is expected to fail it. A planted-drift run gives the gate
something it should pass.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np

from swing_backtest.domain import TradeDirection
from swing_backtest.trades import ExitReason, TradeResult


@dataclass(frozen=True)
class Bars:
    ticker: str
    dates: tuple[date, ...]
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray


@dataclass(frozen=True)
class BracketRules:
    risk_pct: float = 3.0
    reward_multiple: float = 2.0
    max_hold_bars: int = 20


def business_days(start: date, count: int) -> tuple[date, ...]:
    days = []
    current = start
    while len(days) < count:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    return tuple(days)


def random_walk_bars(
    ticker: str,
    dates: tuple[date, ...],
    rng: np.random.Generator,
    daily_vol: float = 0.015,
    drift: float = 0.0,
) -> Bars:
    """Daily OHLC from a geometric random walk with log-return drift `drift` per bar."""
    n = len(dates)
    close = 100.0 * np.exp(np.cumsum(rng.normal(drift, daily_vol, n)))
    prev_close = np.concatenate(([100.0], close[:-1]))
    open_ = prev_close * np.exp(rng.normal(0.0, daily_vol / 4, n))
    wick = np.abs(rng.normal(0.0, daily_vol / 2, (2, n)))
    high = np.maximum(open_, close) * np.exp(wick[0])
    low = np.minimum(open_, close) * np.exp(-wick[1])
    return Bars(ticker, dates, open_, high, low, close)


def simulate_long(
    bars: Bars,
    entry_index: int,
    rules: BracketRules,
    family: str,
    candidate_id: str,
) -> TradeResult | None:
    """Enter at the close of entry_index; exit at stop, target or the last held close.

    A gap through a level at the open fills at the open. A bar that opens between the levels
    and touches both counts as a stop.
    Returns None when fewer than max_hold_bars bars follow the entry.
    """
    last = entry_index + rules.max_hold_bars
    if last >= len(bars.dates):
        return None
    entry = float(bars.close[entry_index])
    stop = entry * (1 - rules.risk_pct / 100)
    target = entry + (entry - stop) * rules.reward_multiple
    exit_index, exit_price, reason = last, float(bars.close[last]), ExitReason.TIME
    for i in range(entry_index + 1, last + 1):
        bar_open = float(bars.open[i])
        if bar_open <= stop:
            exit_index, exit_price, reason = i, bar_open, ExitReason.STOP
            break
        if bar_open >= target:
            exit_index, exit_price, reason = i, bar_open, ExitReason.TARGET
            break
        if bars.low[i] <= stop:
            exit_index, exit_price, reason = i, stop, ExitReason.STOP
            break
        if bars.high[i] >= target:
            exit_index, exit_price, reason = i, target, ExitReason.TARGET
            break
    return TradeResult(
        candidate_id=candidate_id,
        ticker=bars.ticker,
        family=family,
        variant="base",
        direction=TradeDirection.CALL,
        as_of=bars.dates[entry_index],
        trigger_date=bars.dates[entry_index],
        entry_date=bars.dates[entry_index],
        entry_price=entry,
        stop_price=stop,
        target_price=target,
        exit_date=bars.dates[exit_index],
        exit_price=exit_price,
        exit_reason=reason,
        r_multiple=(exit_price - entry) / (entry - stop),
        bars_held=exit_index - entry_index,
        max_hold_bars=rules.max_hold_bars,
    )


def random_entry_family(
    universe: list[Bars],
    family: str,
    n_entries: int,
    rules: BracketRules,
    rng: np.random.Generator,
) -> tuple[tuple[TradeResult, ...], dict[str, float]]:
    """Random long entries plus, per entry, a control trade on a random other date.

    Returns (results, control R by candidate_id).
    """
    results: list[TradeResult] = []
    control_r: dict[str, float] = {}
    usable = len(universe[0].dates) - rules.max_hold_bars - 1
    for k in range(n_entries):
        bars = universe[int(rng.integers(len(universe)))]
        candidate_id = f"{family}-{k:05d}"
        result = simulate_long(bars, int(rng.integers(usable)), rules, family, candidate_id)
        control = simulate_long(bars, int(rng.integers(usable)), rules, "control", candidate_id)
        if result is None or control is None:
            continue
        results.append(result)
        control_r[candidate_id] = control.r_multiple
    return tuple(results), control_r
