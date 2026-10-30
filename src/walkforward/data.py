"""Load one-minute bars and add session columns.

Timestamps with a UTC offset or zone are converted through UTC to
America/New_York and kept as naive Eastern wall time. Naive timestamps are
taken to be Eastern wall time already. A column that mixes the two is rejected.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")
MARKET_TZ = "America/New_York"


def load_bars(path: str | Path) -> pd.DataFrame:
    """Read a CSV or Parquet file of bars and add date, session_id and minute_of_day."""
    path = Path(path)
    if path.suffix == ".parquet":
        bars = pd.read_parquet(path)
    elif path.suffix == ".csv":
        bars = pd.read_csv(path)
    else:
        raise ValueError(f"unsupported bar file type: {path.suffix} (use .csv or .parquet)")
    missing = [c for c in REQUIRED_COLUMNS if c not in bars.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {', '.join(missing)}")
    return add_session_columns(bars)


def add_session_columns(bars: pd.DataFrame) -> pd.DataFrame:
    """Return a sorted copy with date, session_id (0-based per trading day) and minute_of_day."""
    out = bars.copy()
    out["timestamp"] = market_timestamps(out["timestamp"])
    out = out.sort_values("timestamp").reset_index(drop=True)
    out["date"] = out["timestamp"].dt.date
    sessions = {d: i for i, d in enumerate(sorted(out["date"].unique()))}
    out["session_id"] = out["date"].map(sessions)
    out["minute_of_day"] = out["timestamp"].dt.hour * 60 + out["timestamp"].dt.minute
    return out


def market_timestamps(values: pd.Series) -> pd.Series:
    """Parse timestamps into naive America/New_York wall time (see the module docstring)."""
    if not pd.api.types.is_datetime64_any_dtype(values):
        aware = values.map(lambda value: pd.Timestamp(value).tzinfo is not None)
        if aware.any() and not aware.all():
            raise ValueError("timestamp column mixes naive values and values with a UTC offset")
        values = pd.to_datetime(values, utc=bool(aware.any()))
    if values.dt.tz is not None:
        values = values.dt.tz_convert(MARKET_TZ).dt.tz_localize(None)
    return values


def split_at(bars: pd.DataFrame, holdout_start: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(rows before holdout_start, rows on or after it), each with a fresh index."""
    cutoff = pd.Timestamp(holdout_start).date()
    train = bars[bars["date"] < cutoff].reset_index(drop=True)
    holdout = bars[bars["date"] >= cutoff].reset_index(drop=True)
    return train, holdout
