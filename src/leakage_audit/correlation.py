"""Correlation screen: features that track a short-horizon forward return too closely.

Ordinary one-minute features rarely exceed |r| = 0.05 against a five-bar forward return.
Anything above the threshold (default 0.15) is a candidate leak to inspect by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

TARGET_PREFIXES = ("fwd_", "mae_", "mfe_", "label_")


@dataclass(frozen=True)
class CorrelationFinding:
    column: str
    abs_r: float
    rows: int


def correlation_audit(
    frame: pd.DataFrame,
    target: str,
    threshold: float = 0.15,
    sample_size: int = 5000,
    seed: int = 42,
    min_rows: int = 100,
    skip_prefixes: tuple[str, ...] = TARGET_PREFIXES,
) -> list[CorrelationFinding]:
    """Numeric columns whose |Pearson r| with `target` exceeds threshold, largest first."""
    rows = frame[frame[target].notna()]
    if len(rows) > sample_size:
        rows = rows.sample(sample_size, random_state=seed)
    findings = []
    for column in rows.select_dtypes(include=[np.number]).columns:
        if column == target or column.startswith(skip_prefixes):
            continue
        pair = rows[[column, target]].replace([np.inf, -np.inf], np.nan).dropna()
        if len(pair) < min_rows or pair[column].std() == 0:
            continue
        r = float(np.corrcoef(pair[column], pair[target])[0, 1])
        if abs(r) > threshold:
            findings.append(CorrelationFinding(column, round(abs(r), 4), len(pair)))
    return sorted(findings, key=lambda f: f.abs_r, reverse=True)
