"""Truncation test: a causal feature at row t is the same whether or not rows after t exist.

Recompute the features on the first `cut` rows and compare with the full-history values on
those rows. Any difference means the feature read data from after the row it describes.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass

import numpy as np
import pandas as pd

FeatureFn = Callable[[pd.DataFrame], pd.DataFrame]


@dataclass(frozen=True)
class TruncationFinding:
    column: str
    cut: int
    mismatched_rows: int
    first_mismatch: int


def truncation_audit(
    bars: pd.DataFrame,
    feature_fn: FeatureFn,
    columns: Sequence[str],
    cut_points: Sequence[int],
    rtol: float = 1e-9,
) -> list[TruncationFinding]:
    full = feature_fn(bars)
    findings = []
    for cut in cut_points:
        partial = feature_fn(bars.iloc[:cut].copy())
        for column in columns:
            expected = full[column].to_numpy(dtype=float)[:cut]
            observed = partial[column].to_numpy(dtype=float)[:cut]
            same = np.isclose(expected, observed, rtol=rtol, atol=0.0, equal_nan=True)
            if not same.all():
                bad = np.flatnonzero(~same)
                findings.append(TruncationFinding(column, cut, len(bad), int(bad[0])))
    return findings


def default_cut_points(n_rows: int, count: int = 5, offset: int = 7) -> list[int]:
    """Evenly spaced cuts, shifted off round numbers so a cut lands inside a bucket or day."""
    step = n_rows // (count + 1)
    return [step * (i + 1) + offset for i in range(count) if step * (i + 1) + offset < n_rows]
