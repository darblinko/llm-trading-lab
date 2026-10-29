"""Classification and per-trade metrics. Trade returns are percentages of entry price."""

from __future__ import annotations

import numpy as np
from sklearn.metrics import accuracy_score, f1_score, precision_score, recall_score, roc_auc_score


def classification_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    y_proba: np.ndarray | None = None,
) -> dict[str, float]:
    metrics = {
        "accuracy": accuracy_score(y_true, y_pred),
        "precision": precision_score(y_true, y_pred, zero_division=0),
        "recall": recall_score(y_true, y_pred, zero_division=0),
        "f1": f1_score(y_true, y_pred, zero_division=0),
    }
    if y_proba is not None and len(np.unique(y_true)) > 1:
        metrics["auc_roc"] = roc_auc_score(y_true, y_proba)
    return {name: round(float(value), 4) for name, value in metrics.items()}


def trade_metrics(net_returns_pct: np.ndarray) -> dict[str, float]:
    """Count, win rate, mean return and profit factor of a set of trade returns."""
    returns = np.asarray(net_returns_pct, dtype=float)
    if returns.size == 0:
        return {"trades": 0, "win_rate_pct": 0.0, "mean_return_pct": 0.0, "profit_factor": 0.0}
    gains = returns[returns > 0].sum()
    losses = -returns[returns < 0].sum()
    if losses > 0:
        factor = gains / losses
    else:
        factor = float("inf") if gains > 0 else 0.0
    return {
        "trades": int(returns.size),
        "win_rate_pct": round(float((returns > 0).mean() * 100), 2),
        "mean_return_pct": round(float(returns.mean()), 4),
        "profit_factor": round(float(factor), 4),
    }
