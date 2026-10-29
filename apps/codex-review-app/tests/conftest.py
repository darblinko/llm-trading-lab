from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pytest
from review_app.calendar import recorded_session
from review_app.records import timestamp
from review_app.store import ReviewStore


@pytest.fixture
def window() -> dict:
    return recorded_session("2026-09-24")


def ts(clock: str) -> int:
    return timestamp(f"2026-09-24T{clock}:00")


def scenario_event(status: str, clock: str, **fields: object) -> dict:
    return {
        "label": "Support reclaim",
        "event_timestamp": f"2026-09-24T{clock}:00-04:00",
        "status": status,
        "direction": "call",
        "setup_type": "mean_reversion",
        "trigger_zone": {"low": 99, "high": 101},
        "target_price": 104,
        "trigger_conditions": ["rsi > 30"],
        "invalidation_conditions": ["price < 98"],
        "source": f"scenarios.jsonl:{clock}:{status}",
        **fields,
    }


def write_rows(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


@pytest.fixture
def store(tmp_path: Path) -> ReviewStore:
    root = tmp_path / "logs"
    write_rows(
        root / "claude/ticks/ticks_2026-09-24.jsonl",
        [
            {"timestamp": "2026-09-24T09:30:20-04:00", "price": 100, "rsi": 31},
            {"timestamp": "2026-09-24T09:33:20-04:00", "price": 102, "rsi": 44},
        ],
    )
    write_rows(
        root / "claude/scenarios/scenarios_2026-09-24.jsonl",
        [
            scenario_event("created", "09:29"),
            scenario_event("triggered", "09:31"),
        ],
    )
    return ReviewStore(root, tmp_path / "app-cache", date(2026, 9, 24))
