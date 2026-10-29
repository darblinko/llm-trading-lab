"""Walk-forward runner: fit per fold, score out of sample, simulate non-overlapping long trades."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from walkforward.folds import Fold, generate_folds
from walkforward.metrics import classification_metrics, trade_metrics
from walkforward.models import ModelFn


@dataclass(frozen=True)
class WalkForwardConfig:
    """Defaults match the original run: 30 initial sessions, 5-session steps, 10-bar horizon."""

    min_train_sessions: int = 30
    step_sessions: int = 5
    mode: str = "expanding"
    horizon: int = 10
    entry_threshold: float = 0.5
    cost_per_side_pct: float = 0.01
    purge_bars: int = 0


@dataclass(frozen=True)
class WalkForwardResult:
    folds: pd.DataFrame
    predictions: pd.DataFrame
    trades: pd.DataFrame
    summary: dict = field(default_factory=dict)


def run_walk_forward(
    bars: pd.DataFrame,
    model_fn: ModelFn,
    feature_columns: tuple[str, ...],
    config: WalkForwardConfig,
    label_column: str = "label_binary",
) -> WalkForwardResult:
    folds = generate_folds(
        bars, config.min_train_sessions, config.step_sessions, config.mode, config.purge_bars
    )
    fold_rows, prediction_frames = [], []
    for fold in folds:
        scored = _score_fold(bars, fold, model_fn, feature_columns, label_column)
        if scored is None:
            continue
        fold_rows.append(scored[0])
        prediction_frames.append(scored[1])
    predictions = (
        pd.concat(prediction_frames, ignore_index=True).sort_values("idx")
        if prediction_frames
        else pd.DataFrame(columns=["idx", "probability", "actual", "fold_id"])
    )
    trades = simulate_trades(predictions, bars["close"].to_numpy(), config)
    summary = trade_metrics(trades["net_return_pct"].to_numpy()) if len(trades) else {}
    return WalkForwardResult(pd.DataFrame(fold_rows), predictions, trades, summary)


def _score_fold(
    bars: pd.DataFrame,
    fold: Fold,
    model_fn: ModelFn,
    feature_columns: tuple[str, ...],
    label_column: str,
) -> tuple[dict, pd.DataFrame] | None:
    columns = list(feature_columns)
    train = bars.iloc[fold.train_idx]
    test = bars.iloc[fold.test_idx]
    train = train[train[label_column].notna()]
    test = test[test[label_column].notna()]
    if len(train) < 100 or len(test) < 10:
        return None
    model = model_fn(np.nan_to_num(train[columns].to_numpy()), train[label_column].to_numpy())
    x_test = np.nan_to_num(test[columns].to_numpy())
    y_test = test[label_column].to_numpy()
    probability = model.predict_proba(x_test)[:, 1]
    metrics = classification_metrics(y_test, model.predict(x_test), probability)
    row = {"fold_id": fold.fold_id, "train_size": len(train), "test_size": len(test), **metrics}
    frame = pd.DataFrame(
        {
            "idx": test.index.to_numpy(),
            "probability": probability,
            "actual": y_test,
            "fold_id": fold.fold_id,
        }
    )
    return row, frame


def simulate_trades(
    predictions: pd.DataFrame,
    close: np.ndarray,
    config: WalkForwardConfig,
) -> pd.DataFrame:
    """Enter long at the close when probability > entry_threshold; exit `horizon` bars later.

    One position at a time. Returns are percentages; cost is charged on both sides.
    """
    trades, busy_until = [], -1
    round_trip = 2 * config.cost_per_side_pct
    for idx, probability in zip(
        predictions["idx"].to_numpy(), predictions["probability"], strict=True
    ):
        idx = int(idx)
        exit_idx = min(idx + config.horizon, len(close) - 1)
        if idx < busy_until or probability <= config.entry_threshold or exit_idx <= idx:
            continue
        gross = (close[exit_idx] / close[idx] - 1) * 100
        trades.append(
            {
                "entry_idx": idx,
                "exit_idx": exit_idx,
                "probability": round(float(probability), 4),
                "gross_return_pct": round(gross, 4),
                "cost_pct": round_trip,
                "net_return_pct": round(gross - round_trip, 4),
            }
        )
        busy_until = exit_idx
    return pd.DataFrame(
        trades,
        columns=[
            "entry_idx",
            "exit_idx",
            "probability",
            "gross_return_pct",
            "cost_pct",
            "net_return_pct",
        ],
    )
