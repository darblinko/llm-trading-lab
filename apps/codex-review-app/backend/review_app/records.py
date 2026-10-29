"""Small readers for the existing, sometimes incomplete, runtime records."""

from __future__ import annotations

import hashlib
import json
import logging
import math
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
# Runtime JSON has heterogeneous fields; keep that flexibility at the adapter boundary.
Row = dict[str, Any]
logger = logging.getLogger(__name__)


def timestamp(value: object) -> int | None:
    """Naive production bar timestamps represent ET, never the machine's timezone."""
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return int((dt if dt.tzinfo else dt.replace(tzinfo=ET)).timestamp())
    except (ValueError, TypeError, OverflowError):
        return None


def number(value: object) -> float | None:
    try:
        result = float(value)  # type: ignore[arg-type]
        return result if math.isfinite(result) else None
    except (ValueError, TypeError, OverflowError):
        return None


def identity(*parts: object) -> str:
    return hashlib.sha256("\x1f".join(map(str, parts)).encode()).hexdigest()[:20]


def source(path: Path, root: Path, line: int | None = None) -> str:
    name = str(path.relative_to(root))
    return f"{name}:{line}" if line else name


def read_text(path: Path, warnings: list[str]) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ""
    except (OSError, UnicodeError) as exc:
        logger.warning("Cannot read %s: %s", path, exc)
        warnings.append(f"Cannot read {path.name}.")
        return ""


def read_jsonl(path: Path, root: Path, warnings: list[str]) -> list[Row]:
    rows: list[Row] = []
    broken = 0
    for line_no, line in enumerate(read_text(path, warnings).splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict):
                raise ValueError("Expected an object")
            if "source" in row:
                row["source_kind"] = row["source"]
            row["source"] = source(path, root, line_no)
            rows.append(row)
        except (ValueError, TypeError):
            broken += 1
    if broken:
        warnings.append(f"{path.name}: skipped {broken} incomplete or malformed records.")
    return rows


def read_json(path: Path, warnings: list[str]) -> Row:
    text = read_text(path, warnings)
    if not text:
        return {}
    try:
        value = json.loads(text)
        if isinstance(value, dict):
            return value
    except ValueError:
        pass
    warnings.append(f"{path.name}: incomplete or malformed JSON.")
    return {}


def timed_rows(rows: list[Row], field: str = "timestamp") -> list[Row]:
    result = []
    for row in rows:
        ts = timestamp(row.get(field))
        if ts is not None:
            result.append({**row, "time": ts})
    return sorted(result, key=lambda row: row["time"])
