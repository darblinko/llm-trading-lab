"""End-to-end test of claude_review.day_payload over a synthetic log tree and fake bar fetch."""

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np
import pandas as pd
from claude_review.chart_time import to_chart_time
from claude_review.day_payload import DaySources, build_day_payload

SESSION = date(2026, 9, 23)
TODAY = date(2026, 9, 24)
LABEL = "VWAP reclaim call"
CONTRACT = "QQQ260923C00745000"


def _at(clock: str) -> str:
    return f"2026-09-23T{clock}-04:00"


def _minute_bars(days: list[date]) -> pd.DataFrame:
    rng = np.random.default_rng(3)
    stamps = [
        pd.Timestamp(day) + pd.Timedelta(minutes=m)
        for day in days
        for m in range(9 * 60 + 30, 16 * 60)
    ]
    close = 745.0 + np.cumsum(rng.normal(0.0, 0.05, len(stamps)))
    return pd.DataFrame(
        {
            "open": close,
            "high": close + 0.05,
            "low": close - 0.05,
            "close": close,
            "volume": 10_000.0,
            "trade_count": 100.0,
            "vwap": close,
        },
        index=pd.DatetimeIndex(stamps),
    )


def _fake_fetch(start: datetime, end: datetime) -> pd.DataFrame:
    return _minute_bars([date(2026, 9, 21), date(2026, 9, 22), SESSION])


def _failing_fetch(start: datetime, end: datetime) -> pd.DataFrame:
    raise ConnectionError("network down")


def _write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def _scenario_fields() -> dict:
    return {
        "label": LABEL,
        "direction": "call",
        "setup_type": "bull_continuation",
        "confidence": "high",
        "ttl_minutes": None,
        "trigger_zone": {"low": 744.0, "high": 745.0},
        "target_price": 747.0,
        "trigger_conditions": ["price > vwap"],
        "invalidation_conditions": ["price < 743.50"],
    }


def _leg_entry(kind: str, decision: str) -> str:
    response = json.dumps(
        {
            "decision": decision,
            "reasoning": f"{kind} says {decision}",
            "key_factors": ["vwap"],
            "case_for": "reclaim",
            "case_against": "fade",
            "verdict": decision,
            "wait_for": None,
        }
    )
    return (
        f"\n---\n\n### Tick #30 | entry_timing:{kind} | 10:00:40 | 30000ms\n\n"
        f"**Model**: `model-{kind}`\n\n"
        f"<details>\n<summary>Human message (40 chars)</summary>\n\n"
        f"```\nLabel: {LABEL}\n```\n\n</details>\n\n"
        f"**Response**:\n```\n{response}\n```\n\n"
    )


def _write_logs(log_dir: Path) -> None:
    ticks = [
        {
            "timestamp": _at(f"10:{m:02d}:05"),
            "price": 745.0 + m / 100,
            "prev_day_high": 748.0,
            "opening_range_high": 746.0,
            "opening_range_low": 744.2,
        }
        for m in range(30)
    ]
    _write_jsonl(log_dir / "ticks" / "ticks_2026-09-23.jsonl", ticks)
    _write_jsonl(
        log_dir / "scenarios" / "scenarios_2026-09-23.jsonl",
        [
            {
                "event_timestamp": _at("09:40:00"),
                "status": "created",
                "source": "initial_thesis",
                **_scenario_fields(),
            },
            {
                "event_timestamp": _at("10:00:05"),
                "status": "triggered",
                **_scenario_fields(),
                "snapshot_at_event": {"price": 744.6},
            },
            {
                "event_timestamp": _at("10:00:05"),
                "status": "entry_timing",
                "decision": "enter_now",
                "reasoning": "Unanimous enter_now (opus=enter_now, astra=enter_now).",
                **_scenario_fields(),
            },
        ],
    )
    metadata = {"direction": "call", "scenario_label": LABEL, "spot_price": 744.7}
    _write_jsonl(
        log_dir / "orders" / "orders_2026-09-23.jsonl",
        [
            {
                "timestamp": _at("10:01:10"),
                "action": "fill",
                "client_order_id": "b1",
                "symbol": CONTRACT,
                "side": "buy",
                "qty_filled": 10,
                "avg_fill_price": 1.50,
                "reason": "",
                "metadata": metadata,
            },
            {
                "timestamp": _at("10:20:10"),
                "action": "fill",
                "client_order_id": "s1",
                "symbol": CONTRACT,
                "side": "sell",
                "qty_filled": 10,
                "avg_fill_price": 2.00,
                "reason": "TP tier 1",
                "metadata": {},
            },
        ],
    )
    trace = log_dir / "traces" / "trace_2026-09-23.md"
    trace.parent.mkdir(parents=True, exist_ok=True)
    trace.write_text(
        "# LLM Trace\n" + _leg_entry("opus", "enter_now") + _leg_entry("astra", "enter_now"),
        encoding="utf-8",
    )


def _build(tmp_path: Path, fetch=_fake_fetch) -> dict:
    log_dir = tmp_path / "logs"
    _write_logs(log_dir)
    sources = DaySources(log_dir=log_dir, cache_dir=tmp_path / "cache", fetch=fetch, today=TODAY)
    return build_day_payload(SESSION, sources)


def test_payload_links_scenario_evaluation_and_trade(tmp_path: Path) -> None:
    payload = _build(tmp_path)
    assert payload["date"] == "2026-09-23" and payload["is_today"] is False
    [scenario] = payload["scenarios"]
    [evaluation] = payload["evaluations"]
    [trade] = payload["trades"]
    assert scenario["status"] == "entered"
    assert scenario["evaluation_ids"] == [evaluation["id"]]
    assert evaluation["scenario_id"] == scenario["id"]
    assert evaluation["link_quality"] == "exact"
    assert evaluation["legs"]["opus"]["reasoning"] == "opus says enter_now"
    assert trade["realized_pnl"] == 500.0
    assert trade["entry"]["time"] == to_chart_time(_at("10:01:10"))
    assert payload["warnings"] == []


def test_payload_has_day_bars_indicators_and_levels(tmp_path: Path) -> None:
    payload = _build(tmp_path)
    assert len(payload["bars"]) == 130
    assert payload["bars"][0]["time"] == to_chart_time("2026-09-23T09:30:00")
    assert set(payload["indicators"]["overlays"]) == {"vwap", "ema_9", "ema_21"}
    assert {"rsi", "macd", "stochrsi", "volume", "rvol"} <= set(
        payload["indicators"]["oscillators"]
    )
    labels = {level["label"] for level in payload["key_levels"]}
    assert {"PDH", "ORH", "ORL"} <= labels
    json.dumps(payload, allow_nan=False)


def test_bar_failure_degrades_to_warning(tmp_path: Path) -> None:
    payload = _build(tmp_path, fetch=_failing_fetch)
    assert payload["bars"] == []
    assert payload["indicators"] == {"overlays": {}, "oscillators": {}}
    assert payload["warnings"][0].startswith("Candles unavailable")
    assert len(payload["scenarios"]) == 1 and len(payload["trades"]) == 1
    assert {"PDH", "ORH"} <= {level["label"] for level in payload["key_levels"]}
