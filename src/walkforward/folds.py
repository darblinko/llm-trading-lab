"""Session-aligned walk-forward folds with an optional purge of label-overlapping rows."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class Fold:
    fold_id: int
    train_idx: np.ndarray
    test_idx: np.ndarray


def generate_folds(
    bars: pd.DataFrame,
    min_train_sessions: int,
    step_sessions: int,
    mode: str = "expanding",
    purge_bars: int = 0,
) -> list[Fold]:
    """Train on sessions [start, end], test on the next step_sessions sessions, repeat.

    mode "expanding" keeps every earlier session; "sliding" keeps the last min_train_sessions.
    purge_bars drops that many rows from the end of each training set, so a target that
    looks purge_bars ahead never reads a test-session price.
    """
    if mode not in ("expanding", "sliding"):
        raise ValueError(f"unknown mode: {mode}")
    if min_train_sessions < 1 or step_sessions < 1:
        raise ValueError("min_train_sessions and step_sessions must be at least 1")
    if purge_bars < 0:
        raise ValueError("purge_bars must be nonnegative")
    sessions = np.sort(bars["session_id"].unique())
    session_of_row = bars["session_id"].to_numpy()
    folds = []
    train_end = min_train_sessions - 1
    while train_end + step_sessions < len(sessions):
        start = 0 if mode == "expanding" else max(0, train_end + 1 - min_train_sessions)
        train_sessions = sessions[start : train_end + 1]
        test_sessions = sessions[train_end + 1 : train_end + 1 + step_sessions]
        train_idx = np.flatnonzero(np.isin(session_of_row, train_sessions))
        test_idx = np.flatnonzero(np.isin(session_of_row, test_sessions))
        train_idx = purge(train_idx, purge_bars)
        if len(train_idx) and len(test_idx):
            folds.append(Fold(len(folds), train_idx, test_idx))
        train_end += step_sessions
    return folds


def purge(train_idx: np.ndarray, purge_bars: int) -> np.ndarray:
    """Drop the last purge_bars training rows."""
    if purge_bars <= 0:
        return train_idx
    return train_idx[:-purge_bars] if len(train_idx) > purge_bars else train_idx[:0]
