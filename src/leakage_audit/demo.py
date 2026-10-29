"""Feature builders for the planted-leak demonstration.

clean_features: the walk-forward features plus the corrected bucket and daily features.
leaky_features: the same plus the two leaky forms. The audit should flag only the leaky ones.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from leakage_audit.patterns import bucket_last, daily_closes, merge_daily, previous_bucket_last
from walkforward.features import FEATURE_COLUMNS, build_features

CLEAN_EXTRA = ("ret_to_prev_5m_close", "ret_to_prior_daily_close")
LEAKY_EXTRA = ("ret_to_5m_bucket_close", "ret_to_same_day_close")


def clean_features(bars: pd.DataFrame) -> pd.DataFrame:
    out = build_features(bars)
    out["ret_to_prev_5m_close"] = np.log(previous_bucket_last(out, "close", 5) / out["close"])
    daily = merge_daily(out[["date"]], daily_closes(out), prior_day=True)["daily_close"]
    out["ret_to_prior_daily_close"] = np.log(daily.to_numpy() / out["close"].to_numpy())
    return out


def leaky_features(bars: pd.DataFrame) -> pd.DataFrame:
    out = clean_features(bars)
    out["ret_to_5m_bucket_close"] = np.log(bucket_last(out, "close", 5) / out["close"])
    daily = merge_daily(out[["date"]], daily_closes(out), prior_day=False)["daily_close"]
    out["ret_to_same_day_close"] = np.log(daily.to_numpy() / out["close"].to_numpy())
    return out


def feature_columns(leaky: bool) -> list[str]:
    return list(FEATURE_COLUMNS) + list(CLEAN_EXTRA) + (list(LEAKY_EXTRA) if leaky else [])
