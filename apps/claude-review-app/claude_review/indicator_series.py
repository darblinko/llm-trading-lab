"""Indicator series for the review chart, computed from 3-min bars with pandas-ta.

Lengths are common defaults (EMA 9/21, RSI 14, StochRSI 14/14/3/3, MACD 12/26/9,
RVOL 10). Each series is computed over the whole warm-up frame (prior sessions
included) and then trimmed to the session day, so the first bars of the day are
warmed up.
"""

from __future__ import annotations

import logging
from datetime import date

import numpy as np
import pandas as pd
import pandas_ta as ta

from claude_review.chart_time import to_chart_time
from claude_review.market_helpers import compute_session_vwap_series
from claude_review.payload_types import Indicators, Oscillator, Point

logger = logging.getLogger(__name__)

EMA_LENGTHS = (9, 21)
RSI_LENGTH = 14
STOCHRSI_LENGTH, STOCHRSI_RSI_LENGTH, STOCHRSI_K, STOCHRSI_D = 14, 14, 3, 3
MACD_FAST, MACD_SLOW, MACD_SIGNAL = 12, 26, 9
RVOL_PERIOD = 10
VALUE_DECIMALS = 4
# Longest warm-up chain (StochRSI: RSI, then stochastic, then K and D smoothing).
WARM_UP_BARS = STOCHRSI_RSI_LENGTH + STOCHRSI_LENGTH + STOCHRSI_K + STOCHRSI_D


def build_indicators(bars_3m: pd.DataFrame, session_date: date) -> Indicators:
    """Overlay and oscillator series for the session day, in chart time, NaN points dropped."""
    if len(bars_3m) < WARM_UP_BARS:
        logger.warning(
            "Only %d 3-min bars for %s (warm-up needs %d); some indicator series are short "
            "or empty",
            len(bars_3m),
            session_date,
            WARM_UP_BARS,
        )
    close = bars_3m["close"]
    volume = bars_3m["volume"]
    day_bars = bars_3m[bars_3m.index.normalize() == pd.Timestamp(session_date)]
    overlays = {
        "vwap": _points(compute_session_vwap_series(day_bars), session_date),
        **{
            f"ema_{length}": _points(ta.ema(close, length=length), session_date)
            for length in EMA_LENGTHS
        },
    }
    oscillators = {
        "rsi": _rsi(close, session_date),
        "stochrsi": _stochrsi(close, session_date),
        "macd": _macd(close, session_date),
        "volume": Oscillator(
            label="Volume", histogram=_points(volume, session_date), lines={}, levels=[]
        ),
        "rvol": _rvol(volume, session_date),
    }
    return Indicators(overlays=overlays, oscillators=oscillators)


def _points(series: pd.Series | None, session_date: date) -> list[Point]:
    """Session-day points of a series; None (too few bars for pandas-ta) gives no points."""
    if series is None or series.empty:
        return []
    day = series[series.index.normalize() == pd.Timestamp(session_date)].dropna()
    return [
        Point(time=to_chart_time(stamp), value=round(float(value), VALUE_DECIMALS))
        for stamp, value in day.items()
    ]


def _column(frame: pd.DataFrame | None, name: str) -> pd.Series | None:
    return None if frame is None else frame[name]


def _rsi(close: pd.Series, session_date: date) -> Oscillator:
    return Oscillator(
        label=f"RSI {RSI_LENGTH}",
        histogram=[],
        lines={"rsi": _points(ta.rsi(close, length=RSI_LENGTH), session_date)},
        levels=[30.0, 70.0],
    )


def _stochrsi(close: pd.Series, session_date: date) -> Oscillator:
    frame = ta.stochrsi(
        close, length=STOCHRSI_LENGTH, rsi_length=STOCHRSI_RSI_LENGTH, k=STOCHRSI_K, d=STOCHRSI_D
    )
    suffix = f"{STOCHRSI_LENGTH}_{STOCHRSI_RSI_LENGTH}_{STOCHRSI_K}_{STOCHRSI_D}"
    return Oscillator(
        label=f"StochRSI {suffix.replace('_', '/')}",
        histogram=[],
        lines={
            "k": _points(_column(frame, f"STOCHRSIk_{suffix}"), session_date),
            "d": _points(_column(frame, f"STOCHRSId_{suffix}"), session_date),
        },
        levels=[20.0, 80.0],
    )


def _macd(close: pd.Series, session_date: date) -> Oscillator:
    frame = ta.macd(close, fast=MACD_FAST, slow=MACD_SLOW, signal=MACD_SIGNAL)
    suffix = f"{MACD_FAST}_{MACD_SLOW}_{MACD_SIGNAL}"
    return Oscillator(
        label=f"MACD {suffix.replace('_', '/')}",
        histogram=_points(_column(frame, f"MACDh_{suffix}"), session_date),
        lines={
            "macd": _points(_column(frame, f"MACD_{suffix}"), session_date),
            "signal": _points(_column(frame, f"MACDs_{suffix}"), session_date),
        },
        levels=[0.0],
    )


def _rvol(volume: pd.Series, session_date: date) -> Oscillator:
    """Bar volume over the mean of the previous RVOL_PERIOD bars."""
    prior_mean = volume.shift(1).rolling(RVOL_PERIOD).mean().replace(0.0, np.nan)
    return Oscillator(
        label=f"RVOL {RVOL_PERIOD}",
        histogram=[],
        lines={"rvol": _points(volume / prior_mean, session_date)},
        levels=[1.0],
    )
