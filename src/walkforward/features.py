"""Price and volume features computed from one-minute OHLCV, using only past and current bars."""

from __future__ import annotations

import numpy as np
import pandas as pd

SESSION_OPEN_MINUTE = 570  # 09:30
SESSION_MINUTES = 389  # 09:30 to 15:59

FEATURE_COLUMNS = (
    "log_return_1",
    "log_return_5",
    "realized_vol_20",
    "rsi_14",
    "macd_hist",
    "bb_position_20",
    "volume_ratio_20",
    "range_20",
    "session_progress",
)


def _rsi(close: pd.Series, period: int) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / period, adjust=False).mean()
    rsi = 100 - 100 / (1 + gain / loss.replace(0, np.nan))
    # Without losses RSI is 100 when prices rose and neutral (50) when they did not move.
    rsi = rsi.mask((loss == 0) & (gain > 0), 100.0)
    return rsi.mask((loss == 0) & (gain == 0), 50.0)


def build_features(bars: pd.DataFrame) -> pd.DataFrame:
    """Return a copy of bars with FEATURE_COLUMNS added."""
    out = bars.copy()
    close = out["close"]
    out["log_return_1"] = np.log(close / close.shift(1))
    out["log_return_5"] = np.log(close / close.shift(5))
    out["realized_vol_20"] = out["log_return_1"].rolling(20).std()
    out["rsi_14"] = _rsi(close, 14)
    macd = close.ewm(span=12, adjust=False).mean() - close.ewm(span=26, adjust=False).mean()
    out["macd_hist"] = macd - macd.ewm(span=9, adjust=False).mean()
    mean_20, std_20 = close.rolling(20).mean(), close.rolling(20).std()
    band = (4 * std_20).replace(0, np.nan)
    out["bb_position_20"] = ((close - (mean_20 - 2 * std_20)) / band).clip(0, 1)
    out["volume_ratio_20"] = out["volume"] / out["volume"].rolling(20).mean().replace(0, np.nan)
    out["range_20"] = (out["high"] - out["low"]).rolling(20).mean() / close
    progress = (out["minute_of_day"] - SESSION_OPEN_MINUTE) / SESSION_MINUTES
    out["session_progress"] = progress.clip(0, 1)
    return out
