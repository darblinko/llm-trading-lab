"""Tests for claude_review.bars: date-range fetch, RTH trim, cache, payload."""

import json
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pytest
from claude_review.bars import (
    BarsUnavailable,
    SessionBars,
    _normalize_alpaca_frame,
    bars_source_id,
    bars_to_payload,
    load_session_bars,
)

ET = ZoneInfo("America/New_York")
SESSION = date(2026, 9, 23)
TODAY = date(2026, 9, 24)
WEEKDAYS = [date(2026, 9, d) for d in (16, 17, 18, 21, 22, 23)]


def _make_minute_bars(days: list[date], seed: int = 7) -> pd.DataFrame:
    """Synthetic 1-min bars from 04:00 to 19:59 ET on each day, tz-naive ET index."""
    rng = np.random.default_rng(seed)
    stamps = [
        pd.Timestamp(day) + pd.Timedelta(minutes=minute)
        for day in days
        for minute in range(4 * 60, 20 * 60)
    ]
    count = len(stamps)
    close = 700.0 + np.cumsum(rng.normal(0.0, 0.05, count))
    return pd.DataFrame(
        {
            "open": close + rng.normal(0.0, 0.02, count),
            "high": close + np.abs(rng.normal(0.0, 0.05, count)),
            "low": close - np.abs(rng.normal(0.0, 0.05, count)),
            "close": close,
            "volume": rng.integers(1_000, 50_000, count).astype(float),
            "trade_count": rng.integers(10, 500, count).astype(float),
            "vwap": close,
        },
        index=pd.DatetimeIndex(stamps),
    )


class RecordingFetch:
    """Fake MinuteFetch that records each requested window."""

    def __init__(self, frame: pd.DataFrame) -> None:
        self.frame = frame
        self.calls: list[tuple[datetime, datetime]] = []

    def __call__(self, start: datetime, end: datetime) -> pd.DataFrame:
        self.calls.append((start, end))
        return self.frame


def _failing_fetch(start: datetime, end: datetime) -> pd.DataFrame:
    raise RuntimeError("network down")


def _cache_path(cache_dir: Path, day: date) -> Path:
    return cache_dir / f"QQQ_1m_{day.isoformat()}.json"


class TestLoadSessionBars:
    def test_requests_seven_day_window_ending_at_close(self, tmp_path: Path) -> None:
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS))
        load_session_bars(SESSION, tmp_path, fetch, TODAY)
        start, end = fetch.calls[0]
        assert start == datetime(2026, 9, 16, 0, 0, tzinfo=ET)
        assert end == datetime(2026, 9, 23, 16, 0, tzinfo=ET)
        assert start.tzinfo is not None and end.tzinfo is not None

    def test_day_minute_is_session_rth_only(self, tmp_path: Path) -> None:
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS))
        result = load_session_bars(SESSION, tmp_path, fetch, TODAY)
        assert isinstance(result, SessionBars)
        assert len(result.day_minute) == 390
        assert set(result.day_minute.index.date) == {SESSION}
        assert result.day_minute.index[0] == pd.Timestamp("2026-09-23 09:30")
        assert result.day_minute.index[-1] == pd.Timestamp("2026-09-23 15:59")
        assert list(result.day_minute.columns[:5]) == ["open", "high", "low", "close", "volume"]

    def test_bars_3m_cover_last_three_sessions(self, tmp_path: Path) -> None:
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS))
        bars_3m = load_session_bars(SESSION, tmp_path, fetch, TODAY).bars_3m
        assert sorted(set(bars_3m.index.date)) == [date(2026, 9, 21), date(2026, 9, 22), SESSION]
        assert len(bars_3m) == 3 * 130
        assert bars_3m.index[0] == pd.Timestamp("2026-09-21 09:30")
        assert bars_3m.index[-1] == pd.Timestamp("2026-09-23 15:57")

    def test_bars_after_session_date_are_ignored(self, tmp_path: Path) -> None:
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS + [TODAY]))
        bars_3m = load_session_bars(SESSION, tmp_path, fetch, TODAY).bars_3m
        assert max(bars_3m.index.date) == SESSION

    def test_three_minute_bar_aggregates_its_minutes(self, tmp_path: Path) -> None:
        minute = _make_minute_bars(WEEKDAYS)
        result = load_session_bars(SESSION, tmp_path, RecordingFetch(minute), TODAY)
        window = minute.loc["2026-09-23 09:30":"2026-09-23 09:32"]
        first = result.bars_3m.loc[pd.Timestamp("2026-09-23 09:30")]
        assert first["open"] == window["open"].iloc[0]
        assert first["high"] == window["high"].max()
        assert first["low"] == window["low"].min()
        assert first["close"] == window["close"].iloc[-1]
        assert first["volume"] == window["volume"].sum()


class TestCache:
    def test_past_day_is_cached_and_reused(self, tmp_path: Path) -> None:
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS))
        first = load_session_bars(SESSION, tmp_path, fetch, TODAY)
        assert _cache_path(tmp_path, SESSION).exists()
        second = load_session_bars(SESSION, tmp_path, _failing_fetch, TODAY)
        pd.testing.assert_frame_equal(first.day_minute, second.day_minute, check_freq=False)
        pd.testing.assert_frame_equal(first.bars_3m, second.bars_3m, check_freq=False)

    def test_cache_is_json_with_rth_minutes(self, tmp_path: Path) -> None:
        load_session_bars(SESSION, tmp_path, RecordingFetch(_make_minute_bars(WEEKDAYS)), TODAY)
        document = json.loads(_cache_path(tmp_path, SESSION).read_text())
        assert len(document["index"]) == 3 * 390
        assert document["index"][0] == "2026-09-21T09:30:00"

    def test_current_day_is_not_cached(self, tmp_path: Path) -> None:
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS))
        load_session_bars(SESSION, tmp_path, fetch, SESSION)
        assert not _cache_path(tmp_path, SESSION).exists()

    def test_refresh_bypasses_cache(self, tmp_path: Path) -> None:
        load_session_bars(SESSION, tmp_path, RecordingFetch(_make_minute_bars(WEEKDAYS)), TODAY)
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS, seed=99))
        result = load_session_bars(SESSION, tmp_path, fetch, TODAY, refresh=True)
        assert len(fetch.calls) == 1
        expected_close = _make_minute_bars(WEEKDAYS, seed=99).loc["2026-09-23 15:59", "close"]
        assert result.day_minute["close"].iloc[-1] == expected_close

    def test_corrupt_cache_is_refetched(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        _cache_path(tmp_path, SESSION).write_text("{not json")
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS))
        result = load_session_bars(SESSION, tmp_path, fetch, TODAY)
        assert len(fetch.calls) == 1
        assert len(result.day_minute) == 390
        assert "2026-09-23" in caplog.text

    def test_cache_without_session_day_is_refetched(self, tmp_path: Path) -> None:
        document = {"columns": ["close"], "index": ["2026-09-22T09:30:00"], "data": [[1.0]]}
        _cache_path(tmp_path, SESSION).write_text(json.dumps(document))
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS))
        result = load_session_bars(SESSION, tmp_path, fetch, TODAY)
        assert len(fetch.calls) == 1
        assert len(result.day_minute) == 390


class TestCacheSource:
    def test_cache_from_another_source_is_refetched(self, tmp_path: Path) -> None:
        sample = RecordingFetch(_make_minute_bars(WEEKDAYS))
        load_session_bars(SESSION, tmp_path, sample, TODAY, source_id="file:a")
        other = RecordingFetch(_make_minute_bars(WEEKDAYS, seed=99))
        result = load_session_bars(SESSION, tmp_path, other, TODAY, source_id="file:b")
        assert len(other.calls) == 1
        expected_close = _make_minute_bars(WEEKDAYS, seed=99).loc["2026-09-23 15:59", "close"]
        assert result.day_minute["close"].iloc[-1] == expected_close

    def test_cache_from_the_same_source_is_reused(self, tmp_path: Path) -> None:
        sample = RecordingFetch(_make_minute_bars(WEEKDAYS))
        load_session_bars(SESSION, tmp_path, sample, TODAY, source_id="file:a")
        load_session_bars(SESSION, tmp_path, _failing_fetch, TODAY, source_id="file:a")

    def test_source_id_changes_when_the_bars_file_changes(self, tmp_path: Path) -> None:
        bars_file = tmp_path / "bars.jsonl"
        bars_file.write_text('{"t": "2026-09-23T13:30:00Z"}\n')
        before = bars_source_id(bars_file)
        bars_file.write_text('{"t": "2026-09-23T13:30:00Z"}\n{"t": "2026-09-23T13:31:00Z"}\n')
        assert bars_source_id(bars_file) != before
        assert bars_source_id(tmp_path / "other.jsonl") != before


class TestFailures:
    def test_fetch_error_raises_bars_unavailable(self, tmp_path: Path) -> None:
        with pytest.raises(BarsUnavailable, match="2026-09-23"):
            load_session_bars(SESSION, tmp_path, _failing_fetch, TODAY)

    def test_empty_fetch_raises_bars_unavailable(self, tmp_path: Path) -> None:
        with pytest.raises(BarsUnavailable, match="2026-09-23"):
            load_session_bars(SESSION, tmp_path, RecordingFetch(pd.DataFrame()), TODAY)

    def test_missing_session_day_raises(self, tmp_path: Path) -> None:
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS[:-1]))
        with pytest.raises(BarsUnavailable, match="2026-09-23"):
            load_session_bars(SESSION, tmp_path, fetch, TODAY)
        assert not _cache_path(tmp_path, SESSION).exists()


class TestNormalizeAlpacaFrame:
    def test_converts_multiindex_utc_frame(self) -> None:
        stamps = pd.DatetimeIndex(["2026-09-23 13:30", "2026-09-23 13:31"], tz="UTC")
        raw = pd.DataFrame(
            {
                "Open": [1.0, 2.0],
                "High": [1.5, 2.5],
                "Low": [0.5, 1.5],
                "Close": [1.2, 2.2],
                "Volume": [10.0, 20.0],
            },
            index=pd.MultiIndex.from_product([["QQQ"], stamps], names=["symbol", "timestamp"]),
        )
        frame = _normalize_alpaca_frame(raw)
        assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
        assert frame.index[0] == pd.Timestamp("2026-09-23 09:30")
        assert frame.index.tz is None

    def test_empty_frame_stays_empty(self) -> None:
        assert _normalize_alpaca_frame(pd.DataFrame()).empty


class TestBarsToPayload:
    def test_only_session_day_in_chart_time(self, tmp_path: Path) -> None:
        fetch = RecordingFetch(_make_minute_bars(WEEKDAYS))
        bars_3m = load_session_bars(SESSION, tmp_path, fetch, TODAY).bars_3m
        payload = bars_to_payload(bars_3m, SESSION)
        assert len(payload) == 130
        first_open = int(datetime(2026, 9, 23, 9, 30, tzinfo=UTC).timestamp())
        assert payload[0]["time"] == first_open
        assert payload[-1]["time"] == first_open + int(
            timedelta(hours=6, minutes=27).total_seconds()
        )
        source = bars_3m.loc[pd.Timestamp("2026-09-23 09:30")]
        assert payload[0]["close"] == pytest.approx(source["close"])
        assert payload[0]["volume"] == source["volume"]
        assert set(payload[0]) == {"time", "open", "high", "low", "close", "volume"}

    def test_day_without_bars_gives_empty_list(self) -> None:
        empty = _make_minute_bars([date(2026, 9, 22)]).iloc[0:0]
        assert bars_to_payload(empty, SESSION) == []
