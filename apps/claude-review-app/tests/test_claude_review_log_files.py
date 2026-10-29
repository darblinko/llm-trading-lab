"""Tests for claude_review.log_files."""

import json
from pathlib import Path

from claude_review.log_files import (
    SessionPaths,
    json_float,
    json_int,
    list_session_days,
    parse_timestamp,
    read_jsonl,
    session_paths,
)


def _write_lines(path: Path, lines: list[str]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _tick(timestamp: str, price: float = 700.0) -> str:
    return json.dumps({"timestamp": timestamp, "price": price})


def test_session_paths_builds_every_daily_file(tmp_path: Path) -> None:
    paths = session_paths(tmp_path, "2026-09-24")

    assert isinstance(paths, SessionPaths)
    assert paths.ticks == tmp_path / "ticks" / "ticks_2026-09-24.jsonl"
    assert paths.scenarios == tmp_path / "scenarios" / "scenarios_2026-09-24.jsonl"
    assert paths.orders == tmp_path / "orders" / "orders_2026-09-24.jsonl"
    assert paths.trace == tmp_path / "traces" / "trace_2026-09-24.md"
    assert paths.trade_prices == tmp_path / "trade_prices" / "trade_prices_2026-09-24.jsonl"


def test_parse_timestamp_converts_to_eastern() -> None:
    stamp = parse_timestamp("2026-09-24T15:30:00+00:00")

    assert stamp is not None
    assert stamp.isoformat() == "2026-09-24T11:30:00-04:00"


def test_parse_timestamp_treats_naive_values_as_eastern() -> None:
    stamp = parse_timestamp("2026-09-24T11:30:00")

    assert stamp is not None
    assert stamp.isoformat() == "2026-09-24T11:30:00-04:00"


def test_parse_timestamp_rejects_bad_values() -> None:
    assert parse_timestamp("not a time") is None
    assert parse_timestamp(None) is None
    assert parse_timestamp(1790262711.2) is None


def test_read_jsonl_missing_file_gives_empty_list(tmp_path: Path) -> None:
    assert read_jsonl(tmp_path / "absent.jsonl", "2026-09-24", "timestamp") == []


def test_read_jsonl_skips_blank_and_partial_lines(tmp_path: Path) -> None:
    path = _write_lines(
        tmp_path / "ticks.jsonl",
        [
            _tick("2026-09-24T10:00:00-04:00", 701.0),
            "",
            "   ",
            _tick("2026-09-24T10:01:00-04:00", 702.0),
            '{"timestamp": "2026-09-24T10:02:00-04:00", "pri',
        ],
    )

    rows = read_jsonl(path, "2026-09-24", "timestamp")

    assert [row["price"] for row in rows] == [701.0, 702.0]


def test_read_jsonl_drops_rows_dated_another_day(tmp_path: Path) -> None:
    path = _write_lines(
        tmp_path / "ticks.jsonl",
        [
            _tick("2026-05-12T10:00:00-04:00", 500.0),
            _tick("2026-09-17T10:00:00-04:00", 716.0),
            _tick("2026-05-19T10:00:00-04:00", 501.0),
        ],
    )

    rows = read_jsonl(path, "2026-09-17", "timestamp")

    assert [row["price"] for row in rows] == [716.0]


def test_read_jsonl_uses_eastern_date_for_utc_timestamps(tmp_path: Path) -> None:
    path = _write_lines(
        tmp_path / "ticks.jsonl",
        [
            _tick("2026-09-18T02:00:00+00:00", 1.0),
            _tick("2026-09-18T14:00:00+00:00", 2.0),
        ],
    )

    rows = read_jsonl(path, "2026-09-17", "timestamp")

    assert [row["price"] for row in rows] == [1.0]


def test_read_jsonl_reads_the_named_timestamp_key(tmp_path: Path) -> None:
    path = _write_lines(
        tmp_path / "scenarios.jsonl",
        [
            json.dumps({"event_timestamp": "2026-09-24T10:25:53-04:00", "label": "A"}),
            json.dumps({"timestamp": "2026-09-24T10:25:53-04:00", "label": "B"}),
        ],
    )

    rows = read_jsonl(path, "2026-09-24", "event_timestamp")

    assert [row["label"] for row in rows] == ["A"]


def test_read_jsonl_skips_non_object_lines(tmp_path: Path) -> None:
    path = _write_lines(
        tmp_path / "ticks.jsonl",
        ["[1, 2, 3]", _tick("2026-09-24T10:00:00-04:00", 701.0)],
    )

    assert len(read_jsonl(path, "2026-09-24", "timestamp")) == 1


def _ticks_file(log_dir: Path, file_date: str, timestamps: list[str]) -> None:
    _write_lines(
        log_dir / "ticks" / f"ticks_{file_date}.jsonl",
        [_tick(stamp) for stamp in timestamps],
    )


def test_list_session_days_newest_first_and_skips_fixture_only_files(tmp_path: Path) -> None:
    _ticks_file(tmp_path, "2026-09-16", ["2026-05-12T10:00:00-04:00"])
    _ticks_file(tmp_path, "2026-09-17", ["2026-05-12T10:00:00-04:00", "2026-09-17T10:00:00-04:00"])
    _ticks_file(tmp_path, "2026-09-18", ["2026-09-18T09:31:00-04:00"])
    _ticks_file(tmp_path, "2026-05-12", ["2026-09-18T09:31:00-04:00"])

    assert list_session_days(tmp_path) == ["2026-09-18", "2026-09-17"]


def test_list_session_days_respects_limit(tmp_path: Path) -> None:
    for day in ("2026-09-21", "2026-09-22", "2026-09-23"):
        _ticks_file(tmp_path, day, [f"{day}T10:00:00-04:00"])

    assert list_session_days(tmp_path, limit=2) == ["2026-09-23", "2026-09-22"]


def test_list_session_days_ignores_unrelated_file_names(tmp_path: Path) -> None:
    _ticks_file(tmp_path, "2026-09-22", ["2026-09-22T10:00:00-04:00"])
    _write_lines(tmp_path / "ticks" / "notes.jsonl", [_tick("2026-09-22T10:00:00-04:00")])

    assert list_session_days(tmp_path) == ["2026-09-22"]


def test_list_session_days_without_ticks_dir(tmp_path: Path) -> None:
    assert list_session_days(tmp_path) == []


def test_json_float_accepts_numbers_and_numeric_strings() -> None:
    assert json_float(716.52) == 716.52
    assert json_float(10) == 10.0
    assert json_float("735.2") == 735.2


def test_json_float_rejects_non_numeric_values() -> None:
    assert json_float(None) is None
    assert json_float(True) is None
    assert json_float("n/a") is None
    assert json_float("nan") is None
    assert json_float({"price": 1}) is None


def test_json_int_truncates_numeric_values() -> None:
    assert json_int(60) == 60
    assert json_int("60") == 60
    assert json_int(None) is None
