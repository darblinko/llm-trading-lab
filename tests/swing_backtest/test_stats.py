"""Stage A statistics: distinct events, two-month-block bootstrap, summaries and the gate."""

from dataclasses import replace
from datetime import date, timedelta

import numpy as np
import pytest

from swing_backtest.domain import TradeDirection
from swing_backtest.stats import (
    GateRules,
    block_bootstrap_ci,
    block_bootstrap_statistics,
    bonferroni_tail,
    compare_to_control,
    distinct_events,
    evaluate_gate,
    summarize,
    two_month_block,
    yearly_mean_r,
)
from swing_backtest.trades import ExitReason, TradeResult

CALL = TradeDirection.CALL
PUT = TradeDirection.PUT
FAST_RULES = GateRules(n_resamples=1000)
RECENT = (2022, 2023, 2024)


def _result(
    entry: date,
    r: float = 1.0,
    *,
    ticker: str = "AAA",
    family: str = "fam",
    variant: str = "v1",
    direction: TradeDirection = CALL,
    as_of: date | None = None,
    exit_date: date | None = None,
    reason: ExitReason = ExitReason.TARGET,
    cid: str | None = None,
    bars_held: int = 3,
) -> TradeResult:
    as_of = as_of or entry - timedelta(days=1)
    exit_date = exit_date or entry + timedelta(days=2)
    cid = cid or f"{ticker}-{family}-{variant}-{direction.value}-{as_of:%Y%m%d}-{entry:%Y%m%d}"
    sign = 1.0 if direction == CALL else -1.0
    return TradeResult(
        candidate_id=cid,
        ticker=ticker,
        family=family,
        variant=variant,
        direction=direction,
        as_of=as_of,
        trigger_date=as_of,
        entry_date=entry,
        entry_price=100.0,
        stop_price=100.0 - sign * 5.0,
        target_price=100.0 + sign * 10.0,
        exit_date=exit_date,
        exit_price=100.0 + sign * 5.0 * r,
        exit_reason=reason,
        r_multiple=r,
        bars_held=bars_held,
        max_hold_bars=10,
    )


# Distinct events


def test_same_entry_keeps_earliest_as_of():
    entry = date(2024, 3, 11)
    late = _result(entry, 2.0, as_of=date(2024, 3, 8))
    early = _result(entry, 1.0, as_of=date(2024, 3, 6))
    assert distinct_events([late, early]) == (early,)


def test_same_entry_and_as_of_ties_by_candidate_id():
    entry = date(2024, 3, 11)
    first = _result(entry, cid="a-id")
    second = _result(entry, cid="b-id")
    assert distinct_events([second, first]) == (first,)


def test_overlap_drops_entry_on_or_before_last_kept_exit():
    kept = _result(date(2024, 1, 2), exit_date=date(2024, 1, 10))
    on_exit = _result(date(2024, 1, 10), exit_date=date(2024, 1, 12))
    after = _result(date(2024, 1, 11), exit_date=date(2024, 1, 15))
    assert distinct_events([after, on_exit, kept]) == (kept, after)


def test_overlap_compares_against_last_kept_not_last_seen():
    first = _result(date(2024, 1, 2), exit_date=date(2024, 1, 10))
    dropped = _result(date(2024, 1, 5), exit_date=date(2024, 1, 20))
    later = _result(date(2024, 1, 12), exit_date=date(2024, 1, 14))
    assert distinct_events([first, dropped, later]) == (first, later)


def test_overlap_across_variants_keeps_first_variant_by_name():
    entry = date(2024, 1, 2)
    a = _result(entry, variant="a_variant")
    b = _result(entry, variant="b_variant")
    assert distinct_events([b, a]) == (a,)


def test_overlap_is_per_ticker_family_and_direction():
    entry = date(2024, 1, 2)
    base = _result(entry, exit_date=date(2024, 1, 10))
    others = [
        _result(date(2024, 1, 3), direction=PUT),
        _result(date(2024, 1, 3), ticker="BBB"),
        _result(date(2024, 1, 3), family="other"),
    ]
    assert len(distinct_events([base, *others])) == 4


def test_output_sorted_by_entry_ticker_family_variant():
    rows = [
        _result(date(2024, 2, 1), ticker="BBB"),
        _result(date(2024, 2, 1), ticker="AAA", family="zeta"),
        _result(date(2024, 2, 1), ticker="AAA", family="alpha"),
        _result(date(2024, 1, 1), ticker="CCC"),
    ]
    out = distinct_events(rows)
    assert [(r.entry_date, r.ticker, r.family) for r in out] == [
        (date(2024, 1, 1), "CCC", "fam"),
        (date(2024, 2, 1), "AAA", "alpha"),
        (date(2024, 2, 1), "AAA", "zeta"),
        (date(2024, 2, 1), "BBB", "fam"),
    ]


# Bootstrap


def test_two_month_block_pairs_consecutive_months():
    assert two_month_block(date(2024, 1, 2)) == two_month_block(date(2024, 2, 29)) == 2024 * 6
    assert two_month_block(date(2024, 3, 1)) == 2024 * 6 + 1
    assert two_month_block(date(2024, 2, 29)) != two_month_block(date(2024, 3, 1))
    assert two_month_block(date(2024, 12, 31)) == 2024 * 6 + 5
    assert two_month_block(date(2025, 1, 1)) == two_month_block(date(2024, 12, 31)) + 1
    assert two_month_block(date(2009, 11, 30)) == two_month_block(date(2009, 12, 1))


def test_block_bootstrap_ci_is_the_two_sided_quantile_of_the_statistics():
    rng = np.random.default_rng(2)
    values = rng.normal(0.2, 1.0, 60).tolist()
    keys = [i // 4 for i in range(60)]
    statistics = block_bootstrap_statistics(values, keys, n_resamples=800, seed=9)
    low, high = block_bootstrap_ci(values, keys, n_resamples=800, confidence=0.8, seed=9)
    assert (low, high) == pytest.approx(tuple(np.quantile(statistics, [0.1, 0.9])))


def test_bootstrap_is_deterministic_per_seed():
    rng = np.random.default_rng(7)
    values = rng.normal(0.3, 1.0, 120).tolist()
    keys = [i // 6 for i in range(120)]
    first = block_bootstrap_ci(values, keys, n_resamples=2000, seed=3)
    assert block_bootstrap_ci(values, keys, n_resamples=2000, seed=3) == first
    assert block_bootstrap_ci(values, keys, n_resamples=2000, seed=4) != first
    assert first[0] < float(np.mean(values)) < first[1]


def test_bootstrap_rejects_bad_input():
    with pytest.raises(ValueError):
        block_bootstrap_ci([], [])
    with pytest.raises(ValueError):
        block_bootstrap_ci([1.0, 2.0], ["a"])
    with pytest.raises(ValueError):
        block_bootstrap_ci([1.0], ["a"], confidence=1.0)


def test_single_block_gives_degenerate_interval():
    low, high = block_bootstrap_ci([1.0, 2.0, 6.0], ["m", "m", "m"], n_resamples=100)
    assert low == pytest.approx(3.0)
    assert high == pytest.approx(3.0)


def test_statistic_is_mean_over_values_not_mean_of_block_means():
    # Blocks: A = [1] (one value), B = [0] * 9. A draw of {A, B} has mean 0.1;
    # a mean of block means would give 0.5. Half the resamples are {A, B}.
    values = [1.0] + [0.0] * 9
    keys = ["A"] + ["B"] * 9
    low, high = block_bootstrap_ci(values, keys, n_resamples=5000, confidence=0.4)
    assert low == pytest.approx(0.1)
    assert high == pytest.approx(0.1)


def test_bootstrap_coverage_on_known_distribution():
    rng = np.random.default_rng(11)
    true_mean = 0.25
    covered = 0
    replications = 300
    for rep in range(replications):
        values = rng.normal(true_mean, 1.0, 200)
        keys = [i // 5 for i in range(200)]
        low, high = block_bootstrap_ci(values, keys, n_resamples=1000, seed=rep)
        covered += low <= true_mean <= high
    assert 0.84 <= covered / replications <= 0.96


def test_block_resampling_widens_interval_for_correlated_blocks():
    rng = np.random.default_rng(5)
    block_means = rng.normal(0.0, 1.0, 30)
    values = np.repeat(block_means, 8).tolist()
    blocked = block_bootstrap_ci(values, [i // 8 for i in range(240)], n_resamples=2000)
    naive = block_bootstrap_ci(values, list(range(240)), n_resamples=2000)
    assert (blocked[1] - blocked[0]) > 2.0 * (naive[1] - naive[0])


# Summaries


def test_summarize_counts_and_rates():
    rows = [
        _result(date(2024, 1, 2), 2.0, reason=ExitReason.TARGET, bars_held=4),
        _result(date(2024, 1, 9), -1.0, reason=ExitReason.STOP, bars_held=2),
        _result(date(2024, 1, 16), 0.5, reason=ExitReason.TIME, bars_held=10),
        _result(date(2024, 1, 23), -0.2, reason=ExitReason.TIME, bars_held=10),
    ]
    summary = summarize(rows)
    assert summary.n == 4
    assert summary.mean_r == pytest.approx(0.325)
    assert summary.median_r == pytest.approx(0.15)
    assert summary.win_rate == pytest.approx(0.5)
    assert (summary.target_rate, summary.stop_rate, summary.time_rate) == (0.25, 0.25, 0.5)
    assert summary.mean_bars_held == pytest.approx(6.5)
    assert summary.total_r == pytest.approx(1.3)


def test_summarize_empty_is_all_zero():
    summary = summarize([])
    assert summary.n == 0
    assert summary.mean_r == 0.0 and summary.total_r == 0.0


def test_yearly_mean_r_keyed_by_entry_year():
    rows = [
        _result(date(2023, 12, 29), 1.0, exit_date=date(2024, 1, 5)),
        _result(date(2024, 1, 8), 3.0),
        _result(date(2024, 2, 8), -1.0),
    ]
    assert yearly_mean_r(rows) == {2023: (1, 1.0), 2024: (2, 1.0)}


def test_compare_to_control_uses_paired_events_only():
    a = _result(date(2024, 1, 2), 2.0, cid="a")
    b = _result(date(2024, 1, 9), -1.0, cid="b")
    comparison = compare_to_control([a, b], {"a": 0.5})
    assert comparison.n_paired == 1
    assert comparison.mean_r == pytest.approx(2.0)
    assert comparison.mean_control_r == pytest.approx(0.5)
    assert comparison.mean_diff_r == pytest.approx(1.5)
    assert compare_to_control([a], {}).mean_diff_r is None


# Gate


def _month_starts() -> list[date]:
    return [date(year, month, 1) for year in range(2019, 2025) for month in range(1, 13)]


def _base_events(r_for=None) -> list[TradeResult]:
    """216 events, 3 per month over 2019 to 2024, R cycling with mean 0.6."""
    cycle = (2.0, -1.0, 1.0, -1.0, 2.0)
    rows = []
    for month_index, start in enumerate(_month_starts()):
        for slot, day in enumerate((3, 12, 21)):
            i = month_index * 3 + slot
            r = cycle[i % 5] if r_for is None else r_for(month_index, i)
            entry = start.replace(day=day)
            rows.append(_result(entry, r, exit_date=entry + timedelta(days=4), cid=f"e{i:03d}"))
    return rows


def _control_below(events, offset=0.3) -> dict[str, float]:
    return {
        e.candidate_id: e.r_multiple - offset + (0.2 if i % 2 else -0.2)
        for i, e in enumerate(events)
    }


def _failed(verdict) -> set[str]:
    return {check.name for check in verdict.checks if not check.passed}


def _check(verdict, name: str):
    (found,) = [check for check in verdict.checks if check.name == name]
    return found


def _two_month_index(month_index: int) -> int:
    """Two-month block of the month_index-th month from January 2019."""
    return month_index // 2


def test_base_case_passes_every_check():
    events = _base_events()
    verdict = evaluate_gate("fam", events, _control_below(events), FAST_RULES, RECENT)
    assert verdict.passed
    assert [c.name for c in verdict.checks] == [
        "min_events",
        "distinct_months",
        "expectancy",
        "bootstrap_ci",
        "recent_years",
        "control",
    ]
    assert _check(verdict, "distinct_months").detail == "72 distinct entry months; minimum 24"
    assert verdict.n_events == 216
    assert verdict.mean_r == pytest.approx(0.6, abs=0.02)
    assert verdict.ci_low > 0
    assert verdict.diff_mean_r == pytest.approx(0.3, abs=0.01)
    assert verdict.diff_ci_low > 0


def test_min_events_fails_alone():
    events = _base_events()
    verdict = evaluate_gate(
        "fam", events, _control_below(events), replace(FAST_RULES, min_events=217), RECENT
    )
    # The control check also needs min_events paired events.
    assert _failed(verdict) == {"min_events", "control"}
    assert not verdict.passed
    assert _check(verdict, "min_events").detail == "216 distinct events; minimum 217"
    assert (
        "minimum 90% of events and 217 paired events, not met" in _check(verdict, "control").detail
    )


def test_distinct_months_fails_alone():
    events = _base_events()
    verdict = evaluate_gate(
        "fam", events, _control_below(events), replace(FAST_RULES, min_distinct_months=73), RECENT
    )
    assert _failed(verdict) == {"distinct_months"}
    assert not verdict.passed
    assert _check(verdict, "distinct_months").detail == "72 distinct entry months; minimum 73"


def _events_in_months(n_months: int) -> list[TradeResult]:
    """7 events in each of n_months months from January 2022, R cycling with mean 0.6."""
    cycle = (2.0, -1.0, 1.0, -1.0, 2.0)
    rows = []
    for month_index in range(n_months):
        start = date(2022 + month_index // 12, month_index % 12 + 1, 1)
        for slot, day in enumerate((1, 4, 8, 12, 16, 20, 24)):
            i = month_index * 7 + slot
            entry = start.replace(day=day)
            rows.append(
                _result(entry, cycle[i % 5], exit_date=entry + timedelta(days=2), cid=f"m{i:03d}")
            )
    return rows


def test_distinct_months_counts_entry_months_against_the_default_minimum():
    assert GateRules().min_distinct_months == 24
    short = _events_in_months(23)
    verdict = evaluate_gate("fam", short, _control_below(short), FAST_RULES, RECENT)
    assert len(short) == 161
    assert _failed(verdict) == {"distinct_months"}
    assert _check(verdict, "distinct_months").detail == "23 distinct entry months; minimum 24"
    enough = _events_in_months(24)
    assert evaluate_gate("fam", enough, _control_below(enough), FAST_RULES, RECENT).passed


def test_distinct_months_counts_months_not_two_month_blocks():
    rows = [
        _result(date(2024, 1, 5)),
        _result(date(2024, 1, 20)),
        _result(date(2024, 2, 5)),
        _result(date(2025, 1, 5)),
    ]
    detail = _check(evaluate_gate("fam", rows, {}, FAST_RULES, RECENT), "distinct_months").detail
    assert detail == "3 distinct entry months; minimum 24"


def test_expectancy_fails_alone():
    events = _base_events()
    verdict = evaluate_gate(
        "fam", events, _control_below(events), replace(FAST_RULES, min_expectancy_r=1.0), RECENT
    )
    assert _failed(verdict) == {"expectancy"}
    assert "minimum 1.000" in _check(verdict, "expectancy").detail


def test_bootstrap_ci_fails_alone():
    # Two-month blocks alternate +5.2 and -4.8: mean 0.2, every year positive, wide CI.
    events = _base_events(
        lambda month_index, i: 5.2 if _two_month_index(month_index) % 2 == 0 else -4.8
    )
    verdict = evaluate_gate("fam", events, _control_below(events), FAST_RULES, RECENT)
    assert _failed(verdict) == {"bootstrap_ci"}
    assert verdict.mean_r == pytest.approx(0.2)
    assert verdict.ci_low < 0 < verdict.ci_high
    assert "90% two-month-block CI of mean R" in _check(verdict, "bootstrap_ci").detail


def test_gate_ci_resamples_two_month_blocks():
    # Single months alternate +5.2 and -4.8, so every two-month block has mean 0.2
    # and the interval collapses onto it.
    events = _base_events(lambda month_index, i: 5.2 if month_index % 2 == 0 else -4.8)
    verdict = evaluate_gate("fam", events, _control_below(events), FAST_RULES, RECENT)
    assert (verdict.ci_low, verdict.ci_high) == (pytest.approx(0.2), pytest.approx(0.2))
    expected = block_bootstrap_ci(
        [e.r_multiple for e in events],
        [two_month_block(e.entry_date) for e in events],
        n_resamples=FAST_RULES.n_resamples,
        confidence=FAST_RULES.ci_confidence,
        seed=FAST_RULES.seed,
    )
    assert (verdict.ci_low, verdict.ci_high) == expected


def test_recent_years_fails_alone():
    events = _base_events()
    verdict = evaluate_gate(
        "fam",
        events,
        _control_below(events),
        replace(FAST_RULES, min_positive_recent_years=4),
        RECENT,
    )
    assert _failed(verdict) == {"recent_years"}
    assert "3 of 3 recent years" in _check(verdict, "recent_years").detail


def test_control_fails_alone_when_mean_difference_negative():
    events = _base_events()
    verdict = evaluate_gate("fam", events, _control_below(events, offset=-0.3), FAST_RULES, RECENT)
    assert _failed(verdict) == {"control"}
    assert verdict.diff_mean_r < 0


def test_control_fails_alone_when_difference_ci_includes_zero():
    events = _base_events()
    blocks = {e.candidate_id: _two_month_index(i // 3) for i, e in enumerate(events)}
    control = {
        e.candidate_id: e.r_multiple - (3.1 if blocks[e.candidate_id] % 2 == 0 else -2.9)
        for e in events
    }
    verdict = evaluate_gate("fam", events, control, FAST_RULES, RECENT)
    assert _failed(verdict) == {"control"}
    assert verdict.diff_mean_r > 0
    assert verdict.diff_ci_low <= 0


def test_control_fails_without_control_values():
    events = _base_events()
    verdict = evaluate_gate("fam", events, {}, FAST_RULES, RECENT)
    assert _failed(verdict) == {"control"}
    assert verdict.control_mean_r is None and verdict.diff_ci_low is None
    assert _check(verdict, "control").detail.startswith("no events with a control value")


def test_control_fails_when_coverage_is_below_the_floor():
    events = _base_events()
    control = {cid: value for cid, value in _control_below(events).items() if int(cid[1:]) % 2 == 0}
    verdict = evaluate_gate("fam", events, control, FAST_RULES, RECENT)
    assert _failed(verdict) == {"control"}
    detail = _check(verdict, "control").detail
    assert detail.startswith("control coverage 108 of 216 events (50.0%); minimum 90% of events")
    assert "not met" in detail and "over 108 of 216 events" in detail


@pytest.mark.parametrize(("dropped", "passed"), [(21, True), (22, False)])
def test_control_coverage_floor_is_ninety_percent_of_events(dropped, passed):
    events = _base_events()
    control = {
        cid: value for cid, value in _control_below(events).items() if int(cid[1:]) >= dropped
    }
    verdict = evaluate_gate("fam", events, control, FAST_RULES, RECENT)
    assert _check(verdict, "control").passed is passed
    assert f"control coverage {216 - dropped} of 216 events" in _check(verdict, "control").detail


def test_control_coverage_needs_min_events_paired_events():
    events = _base_events()[:200]
    control = _control_below(events)
    rules = replace(FAST_RULES, min_events=150)
    assert _check(evaluate_gate("fam", events, control, rules, RECENT), "control").passed
    few = {cid: v for cid, v in control.items() if int(cid[1:]) < 140}
    small = evaluate_gate("fam", events[:140], few, rules, RECENT)
    assert not _check(small, "control").passed
    assert "minimum 90% of events and 150 paired events, not met" in _check(small, "control").detail


def test_recent_year_counting():
    rows = [
        _result(date(2022, 3, 1), 1.0),
        _result(date(2022, 6, 1), -0.5),
        _result(date(2023, 3, 1), -1.0),
        _result(date(2023, 6, 1), 0.5),
        _result(date(2024, 3, 1), 2.0),
        _result(date(2021, 3, 1), 1.0),
        _result(date(2021, 6, 1), -1.0),
    ]
    years = (2021, 2022, 2023, 2024, 2025)
    rules = replace(FAST_RULES, min_positive_recent_years=2)
    check = _check(evaluate_gate("fam", rows, {}, rules, years), "recent_years")
    assert check.passed
    assert "mean R > 0 in 2 of 5 recent years" in check.detail
    assert "2021: 0.000 over 2" in check.detail
    assert "2025: no events" in check.detail
    stricter = replace(FAST_RULES, min_positive_recent_years=3)
    assert not _check(evaluate_gate("fam", rows, {}, stricter, years), "recent_years").passed


def test_empty_family_fails_every_check():
    verdict = evaluate_gate("fam", [], {}, FAST_RULES, RECENT)
    assert not verdict.passed
    assert _failed(verdict) == {
        "min_events",
        "distinct_months",
        "expectancy",
        "bootstrap_ci",
        "recent_years",
        "control",
    }
    assert verdict.bonferroni_ci_low is None
    assert verdict.passes_bonferroni is False
    assert verdict.ci_low is None


# Bonferroni


def _gate_statistics(events, rules) -> np.ndarray:
    return block_bootstrap_statistics(
        [e.r_multiple for e in events],
        [two_month_block(e.entry_date) for e in events],
        n_resamples=rules.n_resamples,
        seed=rules.seed,
    )


def test_bonferroni_tail():
    assert bonferroni_tail(0.90, 1) == pytest.approx(0.05)
    assert bonferroni_tail(0.90, 8) == pytest.approx(0.00625)
    with pytest.raises(ValueError):
        bonferroni_tail(0.90, 0)
    with pytest.raises(ValueError):
        bonferroni_tail(1.0, 4)


def test_bonferroni_bound_for_one_family_is_the_lower_tail_quantile():
    events = _base_events()
    verdict = evaluate_gate("fam", events, _control_below(events), FAST_RULES, RECENT)
    statistics = _gate_statistics(events, FAST_RULES)
    assert verdict.n_families == 1
    assert verdict.bonferroni_ci_low == pytest.approx(float(np.quantile(statistics, 0.05)))
    assert verdict.ci_low == pytest.approx(float(np.quantile(statistics, 0.05)))
    assert verdict.passes_bonferroni is True


def test_bonferroni_bound_falls_as_the_family_count_grows():
    events = _base_events()
    control = _control_below(events)
    statistics = _gate_statistics(events, FAST_RULES)
    one = evaluate_gate("fam", events, control, FAST_RULES, RECENT, n_families=1)
    eight = evaluate_gate("fam", events, control, FAST_RULES, RECENT, n_families=8)
    assert eight.n_families == 8
    assert eight.bonferroni_ci_low == pytest.approx(float(np.quantile(statistics, 0.00625)))
    assert eight.bonferroni_ci_low < one.bonferroni_ci_low
    assert (eight.passed, eight.ci_low, eight.checks) == (one.passed, one.ci_low, one.checks)


def test_passes_bonferroni_can_fail_while_the_gate_passes():
    # Two-month blocks alternate +2.6 and -1.4: mean 0.6 and a plain lower bound
    # just above 0; the bound for 8 families falls below 0.
    events = _base_events(
        lambda month_index, i: 2.6 if _two_month_index(month_index) % 2 == 0 else -1.4
    )
    verdict = evaluate_gate("fam", events, _control_below(events), FAST_RULES, RECENT, n_families=8)
    assert verdict.passed
    assert verdict.ci_low > 0
    assert verdict.bonferroni_ci_low <= 0
    assert verdict.passes_bonferroni is False


def test_passes_bonferroni_needs_the_other_checks():
    events = _base_events()
    verdict = evaluate_gate(
        "fam", events, _control_below(events, offset=-0.3), FAST_RULES, RECENT, n_families=8
    )
    assert verdict.bonferroni_ci_low > 0
    assert _failed(verdict) == {"control"}
    assert verdict.passes_bonferroni is False


@pytest.mark.parametrize("n_families", [0, -1])
def test_n_families_below_one_raises(n_families):
    with pytest.raises(ValueError, match="n_families"):
        evaluate_gate("fam", _base_events(), {}, FAST_RULES, RECENT, n_families=n_families)
