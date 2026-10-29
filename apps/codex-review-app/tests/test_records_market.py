from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from conftest import ts
from review_app.calendar import recent_sessions
from review_app.market import archive_snapshot, normalize_candles, resample_minutes, save_candles
from review_app.records import number, read_jsonl, timestamp


@pytest.mark.parametrize(
    ("local", "utc"),
    [
        ("2026-09-24T09:30:00", "2026-09-24T13:30:00Z"),
        ("2026-01-05T09:30:00", "2026-01-05T14:30:00Z"),
    ],
)
def test_naive_bar_times_are_eastern_across_dst(local: str, utc: str) -> None:
    assert timestamp(local) == timestamp(utc)


@pytest.mark.parametrize("value", [None, "bad", float("nan"), float("inf")])
def test_nonfinite_numbers_are_unavailable(value: object) -> None:
    assert number(value) is None


def test_jsonl_tolerates_partial_tail_and_retains_provenance(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text('{"source":"refresh","label":"A"}\nnot json\n{"unfinished":')
    warnings = []
    rows = read_jsonl(path, tmp_path, warnings)
    assert rows[0]["source"] == "events.jsonl:1"
    assert rows[0]["source_kind"] == "refresh"
    assert "2 incomplete" in warnings[0]


def test_alpaca_calendar_controls_holidays_and_early_close(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()
    days = ["2026-11-19", "2026-11-20", "2026-11-23", "2026-11-24", "2026-11-25", "2026-11-27"]
    (cache / "calendar.json").write_text(
        json.dumps(
            {
                "start": "2026-10-01",
                "end": "2026-12-01",
                "sessions": [
                    {
                        "date": day,
                        "open": "09:30",
                        "close": "13:00" if day.endswith("27") else "16:00",
                    }
                    for day in days
                ],
            }
        )
    )
    sessions = recent_sessions(tmp_path, cache, "claude", date(2026, 11, 28))
    assert [s["date"] for s in sessions] == list(reversed(days))
    assert sessions[0]["close"] == timestamp("2026-11-27T13:00:00-05:00")
    assert all(s["calendar_verified"] for s in sessions)


def test_calendar_missing_uses_recorded_dates_without_inventing_sessions(store) -> None:
    data = store.catalog("claude")
    assert [s["date"] for s in data["sessions"]] == ["2026-09-24"]
    assert data["sessions"][0]["calendar_verified"] is False


def test_resample_uses_real_ohlc_and_excludes_after_close(window: dict) -> None:
    rows = [
        {
            "ts": "2026-09-24T09:30:00",
            "open": 100,
            "high": 103,
            "low": 99,
            "close": 102,
            "volume": 10,
        },
        {
            "ts": "2026-09-24T09:31:00",
            "open": 102,
            "high": 104,
            "low": 101,
            "close": 103,
            "volume": 20,
        },
        {
            "ts": "2026-09-24T09:32:00",
            "open": 103,
            "high": 105,
            "low": 98,
            "close": 99,
            "volume": 30,
        },
        {"ts": "2026-09-24T16:00:00", "open": 999, "high": 999, "low": 999, "close": 999},
    ]
    assert resample_minutes(rows, window) == [
        {"time": ts("09:30"), "open": 100, "high": 105, "low": 98, "close": 99, "volume": 60}
    ]
    assert normalize_candles([{"time": ts("09:30"), "price": 100}], window) == []


def test_archive_preserves_previous_days_and_excludes_unfinished_bars(tmp_path: Path) -> None:
    root, cache = tmp_path / "logs", tmp_path / "cache"
    (root / "shared").mkdir(parents=True)
    rows = [
        {"ts": f"2026-09-24T{clock}:00", "open": 100, "high": 101, "low": 99, "close": 100}
        for clock in ("09:30", "09:33")
    ]
    (root / "shared/snapshot.json").write_text(
        json.dumps({"produced_at_et": "2026-09-24T09:34:00", "today_bars": rows})
    )
    save_candles(cache, "2026-09-23", [{"time": ts("09:30"), "close": 90}], "test")
    archive_snapshot(root, cache)
    data = json.loads((cache / "candles/QQQ_2026-09-24.json").read_text())
    assert len(data["bars"]) == 1
    assert data["bars"][0]["time"] == ts("09:30")
    assert (cache / "candles/QQQ_2026-09-23.json").exists()


def test_archive_rejects_stale_previous_day_bars(tmp_path: Path) -> None:
    root = tmp_path / "logs"
    (root / "shared").mkdir(parents=True)
    (root / "shared/snapshot.json").write_text(
        json.dumps(
            {
                "produced_at_et": "2026-09-25T09:34:00",
                "today_bars": [
                    {"ts": "2026-09-24T09:30:00", "open": 100, "high": 101, "low": 99, "close": 100}
                ],
            }
        )
    )
    archive_snapshot(root, tmp_path / "cache")
    assert not (tmp_path / "cache/candles/QQQ_2026-09-25.json").exists()
