"""Run the Stage A gate on synthetic data: one family of random entries, one that peeks ahead.

Usage: python -m swing_backtest.demo [--seed N] [--entries N]

The random family has no edge by construction and is expected to fail. The peeking family
chooses entries using the next five closes; it passes, which shows that the gate measures
expectancy and cannot detect look-ahead. The leakage audit is a separate step.
"""

from __future__ import annotations

import argparse
from datetime import date

import numpy as np

from swing_backtest.stats import GateRules, GateVerdict, distinct_events, evaluate_gate
from swing_backtest.synthetic import (
    Bars,
    BracketRules,
    business_days,
    random_entry_family,
    random_walk_bars,
    simulate_long,
)

START = date(2016, 1, 4)
N_BARS = 1512
N_TICKERS = 20
RECENT_YEARS = (2019, 2020, 2021)
PEEK_BARS = 5


def peeking_family(
    universe: list[Bars],
    n_entries: int,
    rules: BracketRules,
    rng: np.random.Generator,
    control_r: dict[str, float],
) -> tuple:
    """Entries kept only when the close PEEK_BARS ahead is higher. Reuses the given controls."""
    results = []
    usable = len(universe[0].dates) - rules.max_hold_bars - 1
    k = 0
    while len(results) < n_entries and k < n_entries * 10:
        bars = universe[int(rng.integers(len(universe)))]
        i = int(rng.integers(usable))
        candidate_id = f"random-{len(results):05d}"
        k += 1
        if candidate_id not in control_r or bars.close[i + PEEK_BARS] <= bars.close[i]:
            continue
        result = simulate_long(bars, i, rules, "peeking", candidate_id)
        if result is not None:
            results.append(result)
    return tuple(results)


def run(seed: int, n_entries: int) -> list[GateVerdict]:
    rng = np.random.default_rng(seed)
    dates = business_days(START, N_BARS)
    universe = [random_walk_bars(f"SYN{t:02d}", dates, rng) for t in range(N_TICKERS)]
    rules = BracketRules()
    random_results, control_r = random_entry_family(universe, "random", n_entries, rules, rng)
    peek_results = peeking_family(universe, n_entries, rules, rng, control_r)
    gate = GateRules()
    return [
        evaluate_gate(name, distinct_events(results), control_r, gate, RECENT_YEARS, 2)
        for name, results in (("random", random_results), ("peeking", peek_results))
    ]


def format_verdict(verdict: GateVerdict) -> str:
    lines = [
        f"{verdict.family}: {'PASS' if verdict.passed else 'FAIL'} "
        f"(events {verdict.n_events}, mean R {verdict.mean_r:.3f})"
    ]
    lines += [
        f"  {'pass' if check.passed else 'FAIL'}  {check.name}: {check.detail}"
        for check in verdict.checks
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--entries", type=int, default=600)
    args = parser.parse_args(argv)
    for verdict in run(args.seed, args.entries):
        print(format_verdict(verdict))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
