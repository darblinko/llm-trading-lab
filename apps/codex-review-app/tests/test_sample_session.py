"""The committed synthetic sample session loads end to end through the store."""

from datetime import date
from pathlib import Path

import pytest
from review_app.market import archive_snapshot
from review_app.store import ReviewStore

SAMPLE_LOGS = Path(__file__).resolve().parents[2] / "sample-session" / "logs"
SAMPLE_DAY = "2026-01-07"


@pytest.mark.skipif(not SAMPLE_LOGS.is_dir(), reason="sample-session/logs not generated")
def test_sample_session_has_candles_scenarios_decisions_and_fills(tmp_path: Path) -> None:
    archive_snapshot(SAMPLE_LOGS, tmp_path)
    store = ReviewStore(SAMPLE_LOGS, tmp_path, date(2026, 1, 7))

    catalog = store.catalog("claude")
    session = store.session(SAMPLE_DAY, "claude")

    assert [s["date"] for s in catalog["sessions"]] == [SAMPLE_DAY]
    assert len(session["candles"]) == 130
    assert [s["label"] for s in session["scenarios"]] == [
        "Opening range breakout",
        "Midday VWAP fade",
        "Afternoon VWAP reclaim",
    ]
    assert len(session["decisions"]) == 4
    assert {f["side"] for f in session["fills"]} == {"buy", "sell"}
    assert all(f["scenario_id"] for f in session["fills"])
    assert session["thesis"].startswith("# Daily thesis")
