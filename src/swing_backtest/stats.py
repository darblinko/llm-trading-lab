"""Stage A statistics: distinct events, two-month-block bootstrap and the family gate.

Holds run up to 30 sessions, longer than a calendar month, so the bootstrap
resamples blocks of two consecutive calendar months of entry dates.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Hashable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date
from statistics import median

import numpy as np

from swing_backtest.trades import ExitReason, TradeResult

# Distinct events


def distinct_events(results: Iterable[TradeResult]) -> tuple[TradeResult, ...]:
    """One result per distinct trade, without overlapping holds.

    Results sharing (ticker, family, variant, direction, entry_date) are one
    trade; the one with the earliest as_of is kept, ties broken by candidate_id.
    Then, per (ticker, family, direction) in entry order, a result whose
    entry_date is on or before the exit_date of the last kept result is dropped.
    Output is sorted by (entry_date, ticker, family, variant).
    """
    unique = _dedupe_same_entry(results)
    kept = _drop_overlaps(unique)
    return tuple(sorted(kept, key=_output_key))


def _dedupe_same_entry(results: Iterable[TradeResult]) -> list[TradeResult]:
    best: dict[tuple, TradeResult] = {}
    for result in results:
        key = (result.ticker, result.family, result.variant, result.direction, result.entry_date)
        current = best.get(key)
        if current is None or (result.as_of, result.candidate_id) < (
            current.as_of,
            current.candidate_id,
        ):
            best[key] = result
    return list(best.values())


def _drop_overlaps(results: Sequence[TradeResult]) -> list[TradeResult]:
    ordered = sorted(results, key=lambda r: (r.entry_date, r.variant, r.as_of, r.candidate_id))
    last_exit: dict[tuple, date] = {}
    kept: list[TradeResult] = []
    for result in ordered:
        key = (result.ticker, result.family, result.direction)
        previous_exit = last_exit.get(key)
        if previous_exit is not None and result.entry_date <= previous_exit:
            continue
        kept.append(result)
        last_exit[key] = result.exit_date
    return kept


def _output_key(result: TradeResult) -> tuple:
    return (
        result.entry_date,
        result.ticker,
        result.family,
        result.variant,
        result.direction.value,
        result.candidate_id,
    )


# Bootstrap


def two_month_block(d: date) -> int:
    """Two-month block key: January and February share one, March and April the next."""
    return d.year * 6 + (d.month - 1) // 2


def block_bootstrap_ci(
    values: Sequence[float],
    block_keys: Sequence[Hashable],
    *,
    n_resamples: int = 5000,
    confidence: float = 0.90,
    seed: int = 0,
) -> tuple[float, float]:
    """Percentile interval of the mean over the resamples of block_bootstrap_statistics."""
    _check_confidence(confidence)
    statistics = block_bootstrap_statistics(
        values,
        block_keys,
        n_resamples=n_resamples,
        seed=seed,
    )
    return _two_sided(statistics, confidence)


def block_bootstrap_statistics(
    values: Sequence[float],
    block_keys: Sequence[Hashable],
    *,
    n_resamples: int = 5000,
    seed: int = 0,
) -> np.ndarray:
    """One resampled mean per resample, from whole blocks drawn with replacement.

    Each resample draws as many blocks as there are distinct blocks. Its
    statistic is the mean over every value in the drawn blocks, so a large
    block weighs more than a small one. Block keys must be sortable.
    """
    values_list = [float(value) for value in values]
    keys_list = list(block_keys)
    if not values_list:
        raise ValueError("block bootstrap needs at least one value")
    if len(values_list) != len(keys_list):
        raise ValueError(f"{len(values_list)} values but {len(keys_list)} block keys")
    if n_resamples < 1:
        raise ValueError(f"n_resamples must be >= 1, got {n_resamples}")
    sums, counts = _block_totals(values_list, keys_list)
    rng = np.random.default_rng(seed)
    draws = rng.integers(0, len(sums), size=(n_resamples, len(sums)))
    return sums[draws].sum(axis=1) / counts[draws].sum(axis=1)


def bonferroni_tail(confidence: float, n_families: int) -> float:
    """Lower tail quantile: the two-sided CI's lower tail, (1 - confidence) / 2.

    The tail is split n_families ways.
    """
    _check_confidence(confidence)
    if n_families < 1:
        raise ValueError(f"n_families must be >= 1, got {n_families}")
    return (1.0 - confidence) / 2.0 / n_families


def _check_confidence(confidence: float) -> None:
    if not 0.0 < confidence < 1.0:
        raise ValueError(f"confidence must be in (0, 1), got {confidence}")


def _two_sided(statistics: np.ndarray, confidence: float) -> tuple[float, float]:
    tail = (1.0 - confidence) / 2.0
    low, high = np.quantile(statistics, [tail, 1.0 - tail])
    return float(low), float(high)


def _block_totals(values: list[float], keys: list[Hashable]) -> tuple[np.ndarray, np.ndarray]:
    sums: dict[Hashable, float] = defaultdict(float)
    counts: dict[Hashable, int] = defaultdict(int)
    for value, key in zip(values, keys, strict=True):
        sums[key] += value
        counts[key] += 1
    order = sorted(sums)
    return (
        np.array([sums[key] for key in order], dtype=float),
        np.array([counts[key] for key in order], dtype=float),
    )


# Summaries


@dataclass(frozen=True)
class Summary:
    """Outcome counts and R statistics of a set of trades. All zeros when n is 0."""

    n: int
    mean_r: float
    median_r: float
    win_rate: float
    target_rate: float
    stop_rate: float
    time_rate: float
    mean_bars_held: float
    total_r: float


def summarize(results: Iterable[TradeResult]) -> Summary:
    """Summary of the given trades. A win is R > 0."""
    rows = tuple(results)
    n = len(rows)
    if n == 0:
        return Summary(0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)
    r_values = [row.r_multiple for row in rows]

    def share(reason: ExitReason) -> float:
        return sum(1 for row in rows if row.exit_reason == reason) / n

    return Summary(
        n=n,
        mean_r=sum(r_values) / n,
        median_r=float(median(r_values)),
        win_rate=sum(1 for value in r_values if value > 0) / n,
        target_rate=share(ExitReason.TARGET),
        stop_rate=share(ExitReason.STOP),
        time_rate=share(ExitReason.TIME),
        mean_bars_held=sum(row.bars_held for row in rows) / n,
        total_r=sum(r_values),
    )


def yearly_mean_r(results: Iterable[TradeResult]) -> dict[int, tuple[int, float]]:
    """{entry year: (event count, mean R)}, years ascending."""
    by_year: dict[int, list[float]] = defaultdict(list)
    for result in results:
        by_year[result.entry_date.year].append(result.r_multiple)
    return {
        year: (len(r_values), sum(r_values) / len(r_values))
        for year, r_values in sorted(by_year.items())
    }


@dataclass(frozen=True)
class ControlComparison:
    """Events that have a control value, against their controls. None when n_paired is 0."""

    n_paired: int
    mean_r: float | None
    mean_control_r: float | None
    mean_diff_r: float | None


def compare_to_control(
    results: Iterable[TradeResult],
    control_r: Mapping[str, float],
) -> ControlComparison:
    events, controls = _paired(tuple(results), control_r)
    if not events:
        return ControlComparison(0, None, None, None)
    n = len(events)
    mean_r = sum(event.r_multiple for event in events) / n
    mean_control = sum(controls) / n
    return ControlComparison(n, mean_r, mean_control, mean_r - mean_control)


def _paired(
    events: Sequence[TradeResult],
    control_r: Mapping[str, float],
) -> tuple[tuple[TradeResult, ...], tuple[float, ...]]:
    kept = tuple(event for event in events if event.candidate_id in control_r)
    return kept, tuple(float(control_r[event.candidate_id]) for event in kept)


# Gate


@dataclass(frozen=True)
class GateRules:
    """Stage A gate thresholds, fixed before any out-of-sample run."""

    min_events: int = 150
    # Distinct calendar months, by entry date, holding at least one event.
    min_distinct_months: int = 24
    min_expectancy_r: float = 0.15
    ci_confidence: float = 0.90
    min_positive_recent_years: int = 2
    # The control check needs a control value for at least this share of the
    # events, and for at least min_events of them.
    min_control_coverage: float = 0.90
    n_resamples: int = 5000
    seed: int = 0


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class GateVerdict:
    """Gate outcome for one family in one period. passed requires every check.

    The Bonferroni fields are informational. bonferroni_ci_low is the lower
    bound of mean R at tail (1 - ci_confidence) / 2 / n_families, so it equals
    ci_low for one family, taken from the same resamples as ci_low. passes_bonferroni applies every
    check with that bound in place of ci_low; passed does not use it.
    """

    family: str
    passed: bool
    n_events: int
    mean_r: float
    ci_low: float | None
    ci_high: float | None
    control_mean_r: float | None
    diff_mean_r: float | None
    diff_ci_low: float | None
    diff_ci_high: float | None
    checks: tuple[GateCheck, ...]
    n_families: int = 1
    bonferroni_ci_low: float | None = None
    passes_bonferroni: bool = False


def evaluate_gate(
    family: str,
    results: Sequence[TradeResult],
    control_r: Mapping[str, float],
    rules: GateRules,
    recent_years: Sequence[int],
    n_families: int = 1,
) -> GateVerdict:
    """Apply every gate check to the distinct events of one family in one period.

    n_families is the number of families the run evaluates; it sets only the
    Bonferroni fields.
    """
    tail = bonferroni_tail(rules.ci_confidence, n_families)
    events = tuple(results)
    summary = summarize(events)
    statistics = _block_statistics([event.r_multiple for event in events], events, rules)
    ci = None if statistics is None else _two_sided(statistics, rules.ci_confidence)
    bonferroni_low = None if statistics is None else float(np.quantile(statistics, tail))
    paired_events, controls = _paired(events, control_r)
    differences = [
        event.r_multiple - control for event, control in zip(paired_events, controls, strict=True)
    ]
    diff_ci = _block_ci(differences, paired_events, rules)
    comparison = compare_to_control(paired_events, control_r)
    checks = (
        _events_check(summary.n, rules),
        _months_check(events, rules),
        _expectancy_check(summary, rules),
        _ci_check(ci, rules),
        _recent_years_check(events, rules, recent_years),
        _control_check(comparison, len(events), diff_ci, rules),
    )
    return GateVerdict(
        family=family,
        passed=all(check.passed for check in checks),
        n_events=summary.n,
        mean_r=summary.mean_r,
        ci_low=ci[0] if ci else None,
        ci_high=ci[1] if ci else None,
        control_mean_r=comparison.mean_control_r,
        diff_mean_r=comparison.mean_diff_r,
        diff_ci_low=diff_ci[0] if diff_ci else None,
        diff_ci_high=diff_ci[1] if diff_ci else None,
        checks=checks,
        n_families=n_families,
        bonferroni_ci_low=bonferroni_low,
        passes_bonferroni=_passes_with_bound(checks, bonferroni_low),
    )


def _block_statistics(
    values: Sequence[float],
    events: Sequence[TradeResult],
    rules: GateRules,
) -> np.ndarray | None:
    if not values:
        return None
    return block_bootstrap_statistics(
        values,
        [two_month_block(event.entry_date) for event in events],
        n_resamples=rules.n_resamples,
        seed=rules.seed,
    )


def _block_ci(
    values: Sequence[float],
    events: Sequence[TradeResult],
    rules: GateRules,
) -> tuple[float, float] | None:
    statistics = _block_statistics(values, events, rules)
    return None if statistics is None else _two_sided(statistics, rules.ci_confidence)


def _passes_with_bound(checks: Sequence[GateCheck], lower_bound: float | None) -> bool:
    """Every check passes, with bootstrap_ci judged on lower_bound > 0."""
    others = all(check.passed for check in checks if check.name != "bootstrap_ci")
    return others and lower_bound is not None and lower_bound > 0


def _events_check(n: int, rules: GateRules) -> GateCheck:
    return GateCheck(
        "min_events",
        n >= rules.min_events,
        f"{n} distinct events; minimum {rules.min_events}",
    )


def _months_check(events: Sequence[TradeResult], rules: GateRules) -> GateCheck:
    months = len({(event.entry_date.year, event.entry_date.month) for event in events})
    return GateCheck(
        "distinct_months",
        months >= rules.min_distinct_months,
        f"{months} distinct entry months; minimum {rules.min_distinct_months}",
    )


def _expectancy_check(summary: Summary, rules: GateRules) -> GateCheck:
    if summary.n == 0:
        return GateCheck(
            "expectancy", False, f"no events; minimum mean R {rules.min_expectancy_r:.3f}"
        )
    return GateCheck(
        "expectancy",
        summary.mean_r >= rules.min_expectancy_r,
        f"mean R {summary.mean_r:.3f}; minimum {rules.min_expectancy_r:.3f}",
    )


def _ci_check(ci: tuple[float, float] | None, rules: GateRules) -> GateCheck:
    label = f"{rules.ci_confidence:.0%} two-month-block CI of mean R"
    if ci is None:
        return GateCheck("bootstrap_ci", False, f"no events; {label} lower bound must exceed 0")
    return GateCheck(
        "bootstrap_ci",
        ci[0] > 0,
        f"{label} [{ci[0]:.3f}, {ci[1]:.3f}]; lower bound must exceed 0",
    )


def _recent_years_check(
    events: Sequence[TradeResult],
    rules: GateRules,
    recent_years: Sequence[int],
) -> GateCheck:
    yearly = yearly_mean_r(events)
    parts = []
    positive = 0
    for year in recent_years:
        if year not in yearly:
            parts.append(f"{year}: no events")
            continue
        count, mean_r = yearly[year]
        if mean_r > 0:
            positive += 1
        parts.append(f"{year}: {mean_r:.3f} over {count}")
    years = "; ".join(parts) if parts else "none listed"
    return GateCheck(
        "recent_years",
        positive >= rules.min_positive_recent_years,
        f"mean R > 0 in {positive} of {len(recent_years)} recent years ({years}); "
        f"minimum {rules.min_positive_recent_years}",
    )


def _control_check(
    comparison: ControlComparison,
    n_events: int,
    diff_ci: tuple[float, float] | None,
    rules: GateRules,
) -> GateCheck:
    rule = "mean and CI lower bound must exceed 0"
    if comparison.mean_diff_r is None or diff_ci is None:
        return GateCheck("control", False, f"no events with a control value; {rule}")
    covered, coverage = _control_coverage(comparison.n_paired, n_events, rules)
    passed = covered and comparison.mean_diff_r > 0 and diff_ci[0] > 0
    return GateCheck(
        "control",
        passed,
        f"{coverage}; R minus control R over {comparison.n_paired} of {n_events} events: "
        f"mean {comparison.mean_diff_r:.3f}, {rules.ci_confidence:.0%} two-month-block CI "
        f"[{diff_ci[0]:.3f}, {diff_ci[1]:.3f}]; {rule}",
    )


def _control_coverage(n_paired: int, n_events: int, rules: GateRules) -> tuple[bool, str]:
    """(whether the paired events meet both coverage floors, the coverage text)."""
    share = n_paired / n_events if n_events else 0.0
    covered = share >= rules.min_control_coverage and n_paired >= rules.min_events
    text = (
        f"control coverage {n_paired} of {n_events} events ({share:.1%}); minimum "
        f"{rules.min_control_coverage:.0%} of events and {rules.min_events} paired events"
        + ("" if covered else ", not met")
    )
    return covered, text
