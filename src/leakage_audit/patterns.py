"""Two look-ahead patterns found in an intraday dataset, each with its corrected form.

1. Bucket "last": groupby(bucket).transform("last") gives every bar in a 5-minute bucket the
   bucket's closing value, so 10:01 sees 10:04. Fix: use the previous completed bucket.
2. Same-day daily merge: joining a daily close on the bar's date lets 09:30 see 16:00.
   Fix: shift the daily series one row before merging.
"""

from __future__ import annotations

import pandas as pd


def bucket_last(bars: pd.DataFrame, column: str, minutes: int) -> pd.Series:
    """Leaky: the last value of each `minutes` bucket, broadcast to every bar in it."""
    bucket = bars["timestamp"].dt.floor(f"{minutes}min")
    return bars.groupby(bucket)[column].transform("last")


def previous_bucket_last(bars: pd.DataFrame, column: str, minutes: int) -> pd.Series:
    """Corrected: the last value of the previous completed bucket in the same session."""
    bucket = bars["timestamp"].dt.floor(f"{minutes}min")
    last = bars.groupby(bucket)[column].last()
    session = last.index.normalize()
    lagged = last.groupby(session).shift(1)
    return bucket.map(lagged)


def merge_daily(bars: pd.DataFrame, daily: pd.DataFrame, prior_day: bool) -> pd.DataFrame:
    """Join daily columns onto bars by date. prior_day=False reproduces the leak."""
    source = daily.sort_values("date").copy()
    if prior_day:
        value_columns = [c for c in source.columns if c != "date"]
        source[value_columns] = source[value_columns].shift(1)
    return bars.merge(source, on="date", how="left")


def daily_closes(bars: pd.DataFrame) -> pd.DataFrame:
    """One row per date with that session's final close, as a daily data vendor would supply."""
    return (
        bars.groupby("date", as_index=False)["close"]
        .last()
        .rename(columns={"close": "daily_close"})
    )
