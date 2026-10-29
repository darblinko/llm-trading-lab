"""Model factories for the walk-forward runner. Each returns fit(X, y) -> fitted model."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import numpy as np
from sklearn.ensemble import RandomForestClassifier

RANDOM_FOREST_DEFAULTS = {
    "n_estimators": 400,
    "max_depth": 10,
    "min_samples_leaf": 20,
    "max_features": "sqrt",
    "class_weight": "balanced",
    "random_state": 42,
    "n_jobs": -1,
}

XGBOOST_DEFAULTS = {
    "max_depth": 5,
    "n_estimators": 300,
    "learning_rate": 0.05,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "min_child_weight": 10,
    "reg_alpha": 0.1,
    "reg_lambda": 1.0,
    "random_state": 42,
    "n_jobs": -1,
    "eval_metric": "logloss",
    "verbosity": 0,
}

ModelFn = Callable[[np.ndarray, np.ndarray], Any]


def random_forest(params: dict | None = None) -> ModelFn:
    settings = {**RANDOM_FOREST_DEFAULTS, **(params or {})}

    def fit(features: np.ndarray, labels: np.ndarray) -> RandomForestClassifier:
        return RandomForestClassifier(**settings).fit(features, labels)

    return fit


def xgboost(params: dict | None = None) -> ModelFn:
    """XGBoost classifier with scale_pos_weight set from the training class balance."""
    try:
        from xgboost import XGBClassifier
    except ImportError as exc:
        raise ImportError("install the xgboost extra: pip install '.[xgboost]'") from exc
    settings = {**XGBOOST_DEFAULTS, **(params or {})}

    def fit(features: np.ndarray, labels: np.ndarray) -> Any:
        positives = int(np.sum(labels == 1))
        weight = (len(labels) - positives) / max(positives, 1)
        return XGBClassifier(scale_pos_weight=weight, **settings).fit(features, labels)

    return fit
