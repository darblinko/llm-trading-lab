"""Load one-minute bars and add session columns."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

REQUIRED_COLUMNS = ("timestamp", "open", "high", "low", "close", "volume")


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
    out["timestamp"] = pd.to_datetime(out["timestamp"])
    out = out.sort_values("timestamp").reset_index(drop=True)
    out["date"] = out["timestamp"].dt.date
    sessions = {d: i for i, d in enumerate(sorted(out["date"].unique()))}
    out["session_id"] = out["date"].map(sessions)
    out["minute_of_day"] = out["timestamp"].dt.hour * 60 + out["timestamp"].dt.minute
    return out


def split_at(bars: pd.DataFrame, holdout_start: str) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(rows before holdout_start, rows on or after it), each with a fresh index."""
    cutoff = pd.Timestamp(holdout_start).date()
    train = bars[bars["date"] < cutoff].reset_index(drop=True)
    holdout = bars[bars["date"] >= cutoff].reset_index(drop=True)
    return train, holdout
