"""Bar and level helpers shared by the bars, indicator and key-level modules.

These follow the conventions of the trading agent's market-data layer: a naive
America/New_York index, lowercase OHLCV columns and 3-minute bars.
"""

from __future__ import annotations

from datetime import datetime, time

import numpy as np
import pandas as pd

SYMBOL = "QQQ"
BAR_INTERVAL_MINUTES = 3
RTH_OPEN_MINUTE = 9 * 60 + 30
RTH_CLOSE_MINUTE = 16 * 60
OPENING_RANGE_START = time(9, 30)
OPENING_RANGE_END = time(9, 45)
OPENING_RANGE_FINAL_MINUTE = time(9, 44)


def filter_rth(bars: pd.DataFrame) -> pd.DataFrame:
    """Keep bars that start between 09:30 and 16:00 ET."""
    if bars.empty or not isinstance(bars.index, pd.DatetimeIndex):
        return bars
    minutes = bars.index.hour * 60 + bars.index.minute
    return bars[(minutes >= RTH_OPEN_MINUTE) & (minutes < RTH_CLOSE_MINUTE)]


def resample_to_3m(bars_1m: pd.DataFrame) -> pd.DataFrame:
    """Aggregate 1-min bars into 3-min bars labelled by their start time."""
    if bars_1m.empty:
        return pd.DataFrame()
    rule = f"{BAR_INTERVAL_MINUTES}min"
    resampled = (
        bars_1m.resample(rule)
        .agg({"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"})
        .dropna(subset=["close"])
    )
    if "trade_count" in bars_1m.columns:
        resampled["trade_count"] = bars_1m["trade_count"].resample(rule).sum()
    if "vwap" in bars_1m.columns:
        resampled["vwap"] = bars_1m["vwap"].resample(rule).last()
    return resampled


def compute_session_vwap_series(today_bars: pd.DataFrame) -> pd.Series:
    """Cumulative session VWAP from typical price (high + low + close) / 3."""
    if today_bars.empty or "volume" not in today_bars.columns:
        return pd.Series(dtype=float)
    typical = (today_bars["high"] + today_bars["low"] + today_bars["close"]) / 3
    volume = today_bars["volume"]
    return (typical * volume).cumsum() / volume.cumsum().replace(0, np.nan)


def compute_opening_range(
    session_bars: pd.DataFrame, now_et: datetime
) -> tuple[float | None, float | None]:
    """High and low of the 09:30 to 09:45 bars, or (None, None) until that window is complete."""
    if not _opening_range_complete(session_bars, now_et):
        return None, None
    clock = session_bars.index.time
    in_window = session_bars[(clock >= OPENING_RANGE_START) & (clock < OPENING_RANGE_END)]
    if in_window.empty:
        return None, None
    return round(float(in_window["high"].max()), 2), round(float(in_window["low"].min()), 2)


def _opening_range_complete(session_bars: pd.DataFrame, now_et: datetime) -> bool:
    if session_bars.empty or now_et.time() < OPENING_RANGE_END:
        return False
    return session_bars.index.max().time() >= OPENING_RANGE_FINAL_MINUTE
