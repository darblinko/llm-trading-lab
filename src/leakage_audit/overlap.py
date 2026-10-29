"""Fold overlap audit: training rows whose forward-looking target reads a test-fold row."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

import numpy as np


class FoldLike(Protocol):
    fold_id: int
    train_idx: np.ndarray
    test_idx: np.ndarray


@dataclass(frozen=True)
class OverlapFinding:
    fold_id: int
    train_rows: int
    overlapping_rows: int


def label_overlap(folds: Iterable[FoldLike], horizon: int) -> list[OverlapFinding]:
    """Per fold, count training rows t where any of t+1 .. t+horizon is a test row."""
    results = []
    for fold in folds:
        test = np.asarray(fold.test_idx)
        train = np.asarray(fold.train_idx)
        reaches = np.zeros(len(train), dtype=bool)
        for step in range(1, horizon + 1):
            reaches |= np.isin(train + step, test)
        results.append(OverlapFinding(fold.fold_id, len(train), int(reaches.sum())))
    return results
