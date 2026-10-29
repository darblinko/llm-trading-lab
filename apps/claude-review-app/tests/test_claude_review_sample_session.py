"""The committed synthetic sample session builds into the day payload stored in fixtures.

Set UPDATE_FIXTURE=1 to rewrite tests/fixtures/sample_day.json after changing the sample.
"""

import json
import os
from datetime import date
from pathlib import Path

import pytest
from claude_review.bars import make_fetch
from claude_review.day_payload import DaySources, build_day_payload

SAMPLE_DIR = Path(__file__).resolve().parents[2] / "sample-session"
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "sample_day.json"
SAMPLE_DAY = date(2026, 1, 7)

pytestmark = pytest.mark.skipif(not SAMPLE_DIR.is_dir(), reason="sample-session not generated")


@pytest.fixture(scope="module")
def payload(tmp_path_factory: pytest.TempPathFactory) -> dict:
    sources = DaySources(
        log_dir=SAMPLE_DIR / "logs" / "claude",
        cache_dir=tmp_path_factory.mktemp("cache"),
        fetch=make_fetch(SAMPLE_DIR / "market" / "QQQ_1m.jsonl"),
        today=date(2026, 1, 8),
    )
    document = json.loads(json.dumps(build_day_payload(SAMPLE_DAY, sources)))
    if os.environ.get("UPDATE_FIXTURE"):
        FIXTURE.write_text(json.dumps(document, indent=1) + "\n")
    return document


def _outline(document: dict) -> dict:
    """The non-numeric structure of a payload, stable across pandas-ta releases."""
    return {
        "date": document["date"],
        "warnings": document["warnings"],
        "bars": len(document["bars"]),
        "key_levels": [level["label"] for level in document["key_levels"]],
        "scenarios": [(s["id"], s["status"], s["evaluation_ids"]) for s in document["scenarios"]],
        "evaluations": [
            (e["id"], e["decision"], e["link_quality"]) for e in document["evaluations"]
        ],
        "trades": [(t["id"], t["qty"], len(t["exits"])) for t in document["trades"]],
    }


def test_sample_day_matches_fixture(payload: dict) -> None:
    assert _outline(payload) == _outline(json.loads(FIXTURE.read_text()))


def test_sample_day_contents(payload: dict) -> None:
    assert payload["warnings"] == []
    assert len(payload["bars"]) == 130
    assert [s["status"] for s in payload["scenarios"]] == ["entered", "expired", "entered"]
    assert [e["link_quality"] for e in payload["evaluations"]] == [
        "exact",
        "exact",
        "missing_trace",
        "exact",
    ]
    assert [len(t["exits"]) for t in payload["trades"]] == [1, 1]
