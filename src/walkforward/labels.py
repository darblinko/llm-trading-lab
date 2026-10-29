"""Forward-return targets.

With within_session=False (the behaviour of the original run) the last `horizon` bars of a
session take their target from the next session's bars. The final training session of each
walk-forward fold therefore reads prices from the first test session; see folds.purge.
"""

from __future__ import annotations

import numpy as np
import pandas as pd


def add_forward_returns(
    bars: pd.DataFrame,
    horizons: tuple[int, ...],
    within_session: bool = False,
) -> pd.DataFrame:
    """Add fwd_return_<h> = (close[t+h] / close[t] - 1) * 100 for each horizon."""
    out = bars.copy()
    for h in horizons:
        future = (
            out.groupby("session_id")["close"].shift(-h)
            if within_session
            else out["close"].shift(-h)
        )
        out[f"fwd_return_{h}"] = (future / out["close"] - 1) * 100
    return out


def add_binary_label(bars: pd.DataFrame, horizon: int, threshold_pct: float) -> pd.DataFrame:
    """label_binary = 1.0 when fwd_return_<horizon> > threshold_pct, NaN when it is unknown."""
    column = f"fwd_return_{horizon}"
    if column not in bars.columns:
        bars = add_forward_returns(bars, (horizon,))
    out = bars.copy()
    forward = out[column]
    out["label_binary"] = np.where(forward.isna(), np.nan, (forward > threshold_pct).astype(float))
    return out
