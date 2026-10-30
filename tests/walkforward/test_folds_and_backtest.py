import numpy as np
import pandas as pd
import pytest

from walkforward import models
from walkforward.backtest import WalkForwardConfig, run_walk_forward, simulate_trades
from walkforward.features import FEATURE_COLUMNS, _rsi, build_features
from walkforward.folds import generate_folds, purge
from walkforward.labels import add_binary_label
from walkforward.metrics import trade_metrics


def test_folds_are_ordered_disjoint_and_session_aligned(bars):
    folds = generate_folds(bars, min_train_sessions=5, step_sessions=2)
    assert len(folds) == 3
    sessions = bars["session_id"].to_numpy()
    for fold in folds:
        assert fold.train_idx.max() < fold.test_idx.min()
        assert not set(sessions[fold.train_idx]) & set(sessions[fold.test_idx])
    sizes = [len(f.train_idx) for f in folds]
    assert sizes == sorted(sizes)


def test_sliding_mode_keeps_fixed_train_window(bars):
    folds = generate_folds(bars, 5, 2, mode="sliding")
    assert len({len(f.train_idx) for f in folds}) == 1
    with pytest.raises(ValueError):
        generate_folds(bars, 5, 2, mode="other")


def test_purge_drops_rows_whose_target_reads_the_test_fold(bars):
    horizon = 10
    unpurged = generate_folds(bars, 5, 2)[0]
    purged = generate_folds(bars, 5, 2, purge_bars=horizon)[0]
    reaches_test = unpurged.train_idx + horizon >= unpurged.test_idx.min()
    assert reaches_test.sum() == horizon
    assert (purged.train_idx + horizon < purged.test_idx.min()).all()
    assert len(purge(np.arange(3), 5)) == 0


def test_features_are_finite_after_warmup(bars):
    features = build_features(bars)[list(FEATURE_COLUMNS)].iloc[40:]
    assert np.isfinite(features.to_numpy()).all()


def test_simulate_trades_charges_cost_and_avoids_overlap():
    predictions = pd.DataFrame({"idx": [0, 1, 2, 3], "probability": [0.9, 0.9, 0.9, 0.1]})
    close = np.array([100.0, 101.0, 102.0, 103.0, 104.0])
    trades = simulate_trades(predictions, close, WalkForwardConfig(horizon=2))
    assert list(trades["entry_idx"]) == [0, 2]
    assert trades["net_return_pct"].iloc[0] == pytest.approx(2.0 - 0.02)


def test_trade_metrics_edge_cases():
    assert trade_metrics(np.array([]))["trades"] == 0
    assert trade_metrics(np.array([1.0, 2.0]))["profit_factor"] == float("inf")
    assert trade_metrics(np.array([1.0, -0.5]))["profit_factor"] == 2.0


def test_random_forest_on_noise_scores_near_chance(bars):
    labelled = build_features(add_binary_label(bars, 10, 0.05))
    config = WalkForwardConfig(min_train_sessions=6, step_sessions=2, purge_bars=10)
    fit = models.random_forest({"n_estimators": 20, "n_jobs": 1})
    result = run_walk_forward(labelled, fit, FEATURE_COLUMNS, config)
    assert len(result.folds) == 3
    assert 0.35 < result.folds["auc_roc"].mean() < 0.65
    assert set(result.trades.columns) >= {"gross_return_pct", "net_return_pct"}


@pytest.mark.parametrize(
    ("min_train", "step", "purge_bars"),
    [(2, 0, 0), (2, -1, 0), (0, 1, 0), (2, 1, -1)],
)
def test_generate_folds_rejects_nonpositive_sizes(bars, min_train, step, purge_bars):
    with pytest.raises(ValueError):
        generate_folds(bars, min_train, step, purge_bars=purge_bars)


def test_rsi_is_100_for_uninterrupted_gains_and_50_for_flat_prices():
    rising = _rsi(pd.Series(np.arange(1.0, 41.0)), 14)
    flat = _rsi(pd.Series(np.full(40, 5.0)), 14)
    assert np.isnan(rising.iloc[0]) and np.isnan(flat.iloc[0])
    assert (rising.iloc[1:] == 100.0).all()
    assert (flat.iloc[1:] == 50.0).all()


def test_rsi_with_losses_is_unchanged():
    close = pd.Series([10.0, 11.0, 10.5, 11.5, 11.0, 12.0])
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / 3, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / 3, adjust=False).mean()
    expected = 100 - 100 / (1 + gain / loss)
    result = _rsi(close, 3)
    assert np.allclose(result.iloc[2:], expected.iloc[2:])
