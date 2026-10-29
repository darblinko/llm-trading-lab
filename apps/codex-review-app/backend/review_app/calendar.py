"""Alpaca session calendar, with explicit offline provenance."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

from review_app.records import Row, read_json, timestamp


def calendar_row(row: Row) -> Row:
    day = str(row["date"])
    return {
        "date": day,
        "open": timestamp(f"{day}T{row['open']}"),
        "close": timestamp(f"{day}T{row['close']}"),
        "calendar_verified": True,
    }


def recent_sessions(root: Path, cache_dir: Path, instance: str, as_of: date) -> list[Row]:
    cache = read_json(cache_dir / "calendar.json", [])
    rows = [calendar_row(row) for row in cache.get("sessions", [])]
    known = {row["date"]: row for row in rows if row["date"] <= as_of.isoformat()}
    covered = cache.get("start", "9999") <= (as_of - timedelta(days=25)).isoformat()
    covered = covered and cache.get("end", "") >= as_of.isoformat()
    if not covered:
        for path in (root / instance / "ticks").glob("ticks_????-??-??.jsonl"):
            day = path.stem.removeprefix("ticks_")
            if day <= as_of.isoformat() and day not in known:
                known[day] = recorded_session(day)
    return [known[day] for day in sorted(known, reverse=True)[:6]]


def recorded_session(day: str) -> Row:
    """Offline chart bounds; never present these as a verified calendar."""
    date.fromisoformat(day)
    return {
        "date": day,
        "open": timestamp(f"{day}T09:30:00"),
        "close": timestamp(f"{day}T16:00:00"),
        "calendar_verified": False,
    }


def session_window(cache_dir: Path, day: str) -> Row:
    for row in read_json(cache_dir / "calendar.json", []).get("sessions", []):
        if row.get("date") == day:
            return calendar_row(row)
    return recorded_session(day)
