"""Tests for claude_review.indicator_series."""

import math
from datetime import UTC, date, datetime

import numpy as np
import pandas as pd
import pytest
from claude_review.indicator_series import build_indicators
from claude_review.payload_types import Indicators, Point

SESSION = date(2026, 9, 23)
DAYS = [date(2026, 9, 21), date(2026, 9, 22), SESSION]
BARS_PER_DAY = 130
DAY_OPEN = int(datetime(2026, 9, 23, 9, 30, tzinfo=UTC).timestamp())
DAY_LAST_BAR = int(datetime(2026, 9, 23, 15, 57, tzinfo=UTC).timestamp())


def _make_session_bars(days: list[date], seed: int = 42) -> pd.DataFrame:
    """Synthetic RTH 3-min bars, 09:30 to 15:57 ET on each day, tz-naive ET index."""
    rng = np.random.default_rng(seed)
    stamps = [
        pd.Timestamp(day) + pd.Timedelta(minutes=570 + 3 * step)
        for day in days
        for step in range(BARS_PER_DAY)
    ]
    count = len(stamps)
    close = 740.0 + np.cumsum(rng.normal(0.02, 0.4, count))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0.0, 0.1, count),
            "high": close + np.abs(rng.normal(0.0, 0.3, count)),
            "low": close - np.abs(rng.normal(0.0, 0.3, count)),
            "close": close,
            "volume": rng.integers(20_000, 400_000, count).astype(float),
        },
        index=pd.DatetimeIndex(stamps),
    )


def _last_value(points: list[Point]) -> float:
    return points[-1]["value"]


@pytest.fixture(scope="module")
def bars() -> pd.DataFrame:
    return _make_session_bars(DAYS)


@pytest.fixture(scope="module")
def indicators(bars: pd.DataFrame) -> Indicators:
    return build_indicators(bars, SESSION)


class TestShape:
    def test_overlay_and_oscillator_keys(self, indicators: Indicators) -> None:
        assert set(indicators["overlays"]) == {"vwap", "ema_9", "ema_21"}
        assert set(indicators["oscillators"]) == {"rsi", "stochrsi", "macd", "volume", "rvol"}

    def test_oscillator_lines_and_levels(self, indicators: Indicators) -> None:
        osc = indicators["oscillators"]
        assert set(osc["rsi"]["lines"]) == {"rsi"} and osc["rsi"]["levels"] == [30.0, 70.0]
        assert set(osc["stochrsi"]["lines"]) == {"k", "d"} and osc["stochrsi"]["levels"] == [
            20.0,
            80.0,
        ]
        assert set(osc["macd"]["lines"]) == {"macd", "signal"} and osc["macd"]["levels"] == [0.0]
        assert osc["volume"]["lines"] == {} and osc["volume"]["levels"] == []
        assert set(osc["rvol"]["lines"]) == {"rvol"} and osc["rvol"]["levels"] == [1.0]
        assert osc["rsi"]["histogram"] == [] and osc["rvol"]["histogram"] == []
        assert len(osc["macd"]["histogram"]) == BARS_PER_DAY
        assert len(osc["volume"]["histogram"]) == BARS_PER_DAY

    def test_labels_are_human_readable(self, indicators: Indicators) -> None:
        labels = {name: osc["label"] for name, osc in indicators["oscillators"].items()}
        assert labels == {
            "rsi": "RSI 14",
            "stochrsi": "StochRSI 14/14/3/3",
            "macd": "MACD 12/26/9",
            "volume": "Volume",
            "rvol": "RVOL 10",
        }


class TestTrimming:
    def test_every_point_is_on_the_session_day(self, indicators: Indicators) -> None:
        series = list(indicators["overlays"].values())
        for osc in indicators["oscillators"].values():
            series.extend(osc["lines"].values())
            series.append(osc["histogram"])
        for points in series:
            assert all(DAY_OPEN <= point["time"] <= DAY_LAST_BAR for point in points)

    def test_warm_up_fills_the_whole_day(self, indicators: Indicators) -> None:
        rsi = indicators["oscillators"]["rsi"]["lines"]["rsi"]
        assert len(rsi) == BARS_PER_DAY
        assert rsi[0]["time"] == DAY_OPEN

    def test_nan_points_are_dropped_without_warm_up(self) -> None:
        day_only = _make_session_bars([SESSION])
        result = build_indicators(day_only, SESSION)
        rsi = result["oscillators"]["rsi"]["lines"]["rsi"]
        signal = result["oscillators"]["macd"]["lines"]["signal"]
        assert 0 < len(rsi) < BARS_PER_DAY
        assert 0 < len(signal) < BARS_PER_DAY
        assert all(math.isfinite(point["value"]) for point in rsi + signal)

    def test_too_few_bars_gives_empty_series(self) -> None:
        tiny = _make_session_bars([SESSION]).iloc[:5]
        result = build_indicators(tiny, SESSION)
        assert result["oscillators"]["rsi"]["lines"]["rsi"] == []
        assert result["overlays"]["ema_21"] == []
        assert len(result["overlays"]["vwap"]) == 5

    def test_input_frame_is_not_modified(self, bars: pd.DataFrame) -> None:
        before = bars.copy()
        build_indicators(bars, SESSION)
        pd.testing.assert_frame_equal(bars, before)


def _wilder_rsi(close: pd.Series, length: int = 14) -> pd.Series:
    change = close.diff()
    gain = change.clip(lower=0).ewm(alpha=1 / length, adjust=False).mean()
    loss = (-change.clip(upper=0)).ewm(alpha=1 / length, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


def _ema(series: pd.Series, length: int) -> pd.Series:
    return series.ewm(span=length, adjust=False).mean()


class TestMatchesReferenceFormulas:
    """The last point of each series equals a plain pandas computation on the same frame."""

    def test_rsi_macd_stochrsi(self, bars: pd.DataFrame, indicators: Indicators) -> None:
        close = bars["close"]
        osc = indicators["oscillators"]
        rsi = _wilder_rsi(close)
        lowest, highest = rsi.rolling(14).min(), rsi.rolling(14).max()
        stoch_k = (100 * (rsi - lowest) / (highest - lowest)).rolling(3).mean()
        macd = _ema(close, 12) - _ema(close, 26)
        signal = _ema(macd, 9)
        assert _last_value(osc["rsi"]["lines"]["rsi"]) == pytest.approx(rsi.iloc[-1], abs=0.01)
        assert _last_value(osc["macd"]["histogram"]) == pytest.approx(
            (macd - signal).iloc[-1], abs=1e-4
        )
        assert _last_value(osc["macd"]["lines"]["signal"]) == pytest.approx(
            signal.iloc[-1], abs=1e-4
        )
        assert _last_value(osc["stochrsi"]["lines"]["k"]) == pytest.approx(
            stoch_k.iloc[-1], abs=0.01
        )
        assert _last_value(osc["stochrsi"]["lines"]["d"]) == pytest.approx(
            stoch_k.rolling(3).mean().iloc[-1], abs=0.01
        )

    def test_emas(self, bars: pd.DataFrame, indicators: Indicators) -> None:
        close = bars["close"]
        for length in (9, 21):
            assert _last_value(indicators["overlays"][f"ema_{length}"]) == pytest.approx(
                _ema(close, length).iloc[-1], abs=1e-4
            )

    def test_rvol_and_volume(self, bars: pd.DataFrame, indicators: Indicators) -> None:
        osc = indicators["oscillators"]
        volume = bars["volume"]
        expected_rvol = volume.iloc[-1] / volume.iloc[-11:-1].mean()
        assert _last_value(osc["rvol"]["lines"]["rvol"]) == pytest.approx(expected_rvol, abs=0.01)
        assert _last_value(osc["volume"]["histogram"]) == volume.iloc[-1]

    def test_session_vwap(self, bars: pd.DataFrame, indicators: Indicators) -> None:
        day = bars[bars.index.normalize() == pd.Timestamp(SESSION)]
        vwap = indicators["overlays"]["vwap"]
        typical = (day["high"] + day["low"] + day["close"]) / 3
        assert vwap[0]["value"] == pytest.approx(typical.iloc[0], abs=1e-4)
        expected = (typical * day["volume"]).sum() / day["volume"].sum()
        assert _last_value(vwap) == pytest.approx(expected, abs=1e-4)
