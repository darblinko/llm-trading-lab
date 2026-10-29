"""Synthetic one-minute bars: a random walk with no predictable structure."""

from __future__ import annotations

import numpy as np
import pandas as pd

BARS_PER_SESSION = 390


def synthetic_minute_bars(
    n_sessions: int,
    seed: int = 0,
    start: str = "2025-01-02",
    minute_vol: float = 0.0006,
) -> pd.DataFrame:
    """OHLCV for n_sessions weekdays of 09:30 to 15:59 bars."""
    rng = np.random.default_rng(seed)
    days = pd.bdate_range(start, periods=n_sessions)
    minutes = pd.timedelta_range("09:30:00", periods=BARS_PER_SESSION, freq="min")
    timestamps = (days.values[:, None] + minutes.values[None, :]).ravel()
    n = len(timestamps)
    close = 400.0 * np.exp(np.cumsum(rng.normal(0.0, minute_vol, n)))
    open_ = np.concatenate(([400.0], close[:-1]))
    wick = np.abs(rng.normal(0.0, minute_vol / 2, (2, n)))
    return pd.DataFrame(
        {
            "timestamp": pd.to_datetime(timestamps),
            "open": open_.round(4),
            "high": (np.maximum(open_, close) * np.exp(wick[0])).round(4),
            "low": (np.minimum(open_, close) * np.exp(-wick[1])).round(4),
            "close": close.round(4),
            "volume": rng.lognormal(8.0, 0.5, n).round().astype(int),
        }
    )
