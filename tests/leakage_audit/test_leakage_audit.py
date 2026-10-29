import numpy as np
import pandas as pd
import pytest

from leakage_audit.__main__ import main
from leakage_audit.barrier import (
    DIAGNOSTIC,
    BalanceRules,
    balance_by_year,
    triple_barrier_labels,
    vertical_share,
)
from leakage_audit.correlation import correlation_audit
from leakage_audit.demo import (
    CLEAN_EXTRA,
    LEAKY_EXTRA,
    clean_features,
    feature_columns,
    leaky_features,
)
from leakage_audit.overlap import label_overlap
from leakage_audit.patterns import bucket_last, daily_closes, merge_daily, previous_bucket_last
from leakage_audit.report import render_markdown, run_audit
from leakage_audit.truncation import default_cut_points, truncation_audit
from walkforward.data import add_session_columns
from walkforward.folds import generate_folds
from walkforward.labels import add_forward_returns
from walkforward.synthetic import synthetic_minute_bars


@pytest.fixture(scope="module")
def bars():
    raw = add_session_columns(synthetic_minute_bars(8, seed=5))
    return add_forward_returns(raw, (5,))


def test_bucket_last_reads_ahead_and_previous_bucket_does_not(bars):
    leaky = bucket_last(bars, "close", 5)
    fixed = previous_bucket_last(bars, "close", 5)
    assert leaky.iloc[0] == bars["close"].iloc[4]
    assert np.isnan(fixed.iloc[0])
    assert fixed.iloc[5] == bars["close"].iloc[4]


def test_daily_merge_prior_day_uses_previous_session(bars):
    daily = daily_closes(bars)
    same = merge_daily(bars[["date"]], daily, prior_day=False)["daily_close"]
    prior = merge_daily(bars[["date"]], daily, prior_day=True)["daily_close"]
    assert same.iloc[0] == bars["close"].iloc[389]
    assert np.isnan(prior.iloc[0])
    assert prior.iloc[390] == bars["close"].iloc[389]


def test_correlation_audit_flags_bucket_leak_only(bars):
    findings = correlation_audit(leaky_features(bars), "fwd_return_5")
    assert findings[0].column == "ret_to_5m_bucket_close"
    assert {f.column for f in findings} <= set(LEAKY_EXTRA)
    assert correlation_audit(clean_features(bars), "fwd_return_5") == []


def test_truncation_audit_flags_both_planted_leaks(bars):
    cuts = default_cut_points(len(bars))
    leaky = truncation_audit(bars, leaky_features, feature_columns(True), cuts)
    assert {f.column for f in leaky} == set(LEAKY_EXTRA)
    clean = truncation_audit(bars, clean_features, feature_columns(False), cuts)
    assert clean == []
    assert set(CLEAN_EXTRA) <= set(feature_columns(False))


def test_label_overlap_counts_horizon_rows_until_purged(bars):
    unpurged = label_overlap(generate_folds(bars, 4, 2), horizon=10)
    purged = label_overlap(generate_folds(bars, 4, 2, purge_bars=10), horizon=10)
    assert [f.overlapping_rows for f in unpurged] == [10, 10]
    assert [f.overlapping_rows for f in purged] == [0, 0]


def test_triple_barrier_labels_and_balance():
    frame = pd.DataFrame(
        {
            "timestamp": pd.date_range("2024-01-02 09:30", periods=6, freq="min"),
            "close": [100.0, 100.0, 100.0, 100.0, 100.0, 100.0],
            "high": [100.0, 101.5, 100.0, 100.0, 100.0, 100.0],
            "low": [100.0, 100.0, 100.0, 98.5, 100.0, 100.0],
        }
    )
    labels = triple_barrier_labels(frame, 1.0, 1.0, 2)
    assert list(labels[:4]) == ["upper", "lower", "lower", "vertical"]
    assert pd.isna(labels.iloc[-1])
    [year] = balance_by_year(labels, frame["timestamp"], BalanceRules())
    assert (year.upper, year.lower, year.vertical, year.status) == (0.25, 0.5, 0.25, "PASS")
    [gate] = balance_by_year(labels, frame["timestamp"], BalanceRules(max_share=0.4))
    assert gate.status == "FAIL"
    [diag] = balance_by_year(
        labels, frame["timestamp"], BalanceRules(max_share=0.4, hard_gate=False)
    )
    assert diag.status == "WARN"
    [diag_default] = balance_by_year(labels, frame["timestamp"], DIAGNOSTIC)
    assert diag_default.status == "PASS"
    assert vertical_share(labels) == 0.25


def test_report_and_cli(bars, tmp_path, capsys):
    folds = generate_folds(bars, 4, 2)
    result = run_audit(bars, leaky_features, feature_columns(True), "fwd_return_5", folds, 10)
    text = render_markdown(result, "t")
    assert result.leak_found and "Leak found: yes" in text
    data = tmp_path / "bars.csv"
    synthetic_minute_bars(36, seed=2).to_csv(data, index=False)
    out = tmp_path / "report.md"
    assert (
        main(["--data", str(data), "--purge-bars", "10", "--out", str(out), "--fail-on-leak"]) == 0
    )
    assert "Leak found: no" in out.read_text()
    assert main(["--data", str(data), "--plant-leaks", "--fail-on-leak"]) == 1
    capsys.readouterr()
