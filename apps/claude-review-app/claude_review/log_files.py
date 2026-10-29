"""Read-only access to the trader's daily log files.

The live trader may be appending to today's files while they are read, so a
partial last line is skipped rather than treated as an error. Some files also
hold test-fixture rows dated other days; rows are kept only when their
timestamp's US/Eastern date equals the session date.
"""

import json
import logging
import math
import re
from collections.abc import Iterator
from datetime import datetime
from pathlib import Path
from typing import Any, NamedTuple
from zoneinfo import ZoneInfo

from claude_review.chart_time import ET_ZONE

logger = logging.getLogger(__name__)

JsonRow = dict[str, Any]

ET = ZoneInfo(ET_ZONE)
TICK_TIMESTAMP_KEY = "timestamp"
_TICKS_FILE_NAME = re.compile(r"^ticks_(\d{4}-\d{2}-\d{2})\.jsonl$")


class SessionPaths(NamedTuple):
    ticks: Path
    scenarios: Path
    orders: Path
    trace: Path
    trade_prices: Path


def session_paths(log_dir: Path, session_date: str) -> SessionPaths:
    """Return the paths of one session's log files under `log_dir`."""
    return SessionPaths(
        ticks=log_dir / "ticks" / f"ticks_{session_date}.jsonl",
        scenarios=log_dir / "scenarios" / f"scenarios_{session_date}.jsonl",
        orders=log_dir / "orders" / f"orders_{session_date}.jsonl",
        trace=log_dir / "traces" / f"trace_{session_date}.md",
        trade_prices=log_dir / "trade_prices" / f"trade_prices_{session_date}.jsonl",
    )


def parse_timestamp(value: object) -> datetime | None:
    """Return an ET-aware datetime for an ISO string; naive values are taken as ET."""
    if not isinstance(value, str):
        return None
    try:
        stamp = datetime.fromisoformat(value)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        return stamp.replace(tzinfo=ET)
    return stamp.astimezone(ET)


def json_float(value: object) -> float | None:
    """Return a finite float from a JSON number or numeric string, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return None
    try:
        number = float(value)
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def json_int(value: object) -> int | None:
    number = json_float(value)
    return int(number) if number is not None else None


def read_jsonl(path: Path, session_date: str, timestamp_key: str) -> list[JsonRow]:
    """Return the rows of a JSONL log dated `session_date` in ET; a missing file gives []."""
    try:
        rows = list(_iter_rows(path))
    except FileNotFoundError:
        return []
    kept = [row for row in rows if _is_dated(row, session_date, timestamp_key)]
    if len(kept) < len(rows):
        logger.info(
            "Dropped %d of %d rows in %s whose %s is missing or not dated %s",
            len(rows) - len(kept),
            len(rows),
            path,
            timestamp_key,
            session_date,
        )
    return kept


def list_session_days(log_dir: Path, limit: int = 6) -> list[str]:
    """Return up to `limit` session dates, newest first, whose ticks file has a row that day."""
    days: list[str] = []
    for session_date in sorted(_tick_file_dates(log_dir), reverse=True):
        if len(days) >= limit:
            break
        if _has_row_dated(session_paths(log_dir, session_date).ticks, session_date):
            days.append(session_date)
    return days


def _iter_rows(path: Path) -> Iterator[JsonRow]:
    """Yield each JSON object line; blank, malformed and non-object lines are skipped."""
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line_number, line in enumerate(handle, start=1):
            text = line.strip()
            if not text:
                continue
            try:
                row = json.loads(text)
            except json.JSONDecodeError:
                logger.warning("Skipping unparseable line %d in %s", line_number, path)
                continue
            if not isinstance(row, dict):
                logger.warning("Skipping non-object line %d in %s", line_number, path)
                continue
            yield row


def _is_dated(row: JsonRow, session_date: str, timestamp_key: str) -> bool:
    stamp = parse_timestamp(row.get(timestamp_key))
    return stamp is not None and stamp.date().isoformat() == session_date


def _tick_file_dates(log_dir: Path) -> list[str]:
    ticks_dir = log_dir / "ticks"
    if not ticks_dir.is_dir():
        return []
    matches = (_TICKS_FILE_NAME.match(path.name) for path in ticks_dir.iterdir())
    return [match.group(1) for match in matches if match]


def _has_row_dated(path: Path, session_date: str) -> bool:
    """Read `path` only until the first row dated `session_date`."""
    rows = _iter_rows(path)
    try:
        return any(_is_dated(row, session_date, TICK_TIMESTAMP_KEY) for row in rows)
    except FileNotFoundError:
        return False
    finally:
        rows.close()
