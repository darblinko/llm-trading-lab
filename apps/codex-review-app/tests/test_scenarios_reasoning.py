from __future__ import annotations

import json
from pathlib import Path

from conftest import scenario_event, ts
from review_app.reasoning import link_decisions, read_decisions
from review_app.scenarios import add_outcomes, reconstruct_scenarios, scenario_at


def scenarios(events: list[dict]) -> list[dict]:
    return reconstruct_scenarios(events, "2026-09-24", "claude", ts("16:00"))


def test_same_label_revisions_remain_distinct_and_time_bounded() -> None:
    rows = scenarios(
        [
            scenario_event("created", "09:29"),
            scenario_event("triggered", "09:35"),
            scenario_event("created", "10:05", target_price=110),
            scenario_event("triggered", "10:06"),
        ]
    )
    assert len(rows) == 2
    assert rows[0]["id"] != rows[1]["id"]
    assert rows[0]["end"] == ts("10:05")
    assert rows[1]["target"] == 110
    assert len(rows[0]["events"]) == len(rows[1]["events"]) == 2
    assert scenario_at(rows, "Support reclaim", ts("10:05"))["id"] == rows[1]["id"]


def test_expiration_limits_zone_and_nonprice_conditions_are_not_lines() -> None:
    rows = scenarios(
        [
            scenario_event(
                "created",
                "10:00",
                ttl_minutes=15,
                invalidation_conditions=["price < 98", "rsi < 30", "price_above_vwap == False"],
            )
        ]
    )
    assert rows[0]["end"] == ts("10:15")
    assert rows[0]["price_invalidations"] == [
        {"operator": "<", "price": 98, "condition": "price < 98"}
    ]


def test_same_bar_target_invalidation_is_unknown_and_pretrigger_bar_excluded() -> None:
    rows = scenarios([scenario_event("created", "09:29"), scenario_event("triggered", "09:31")])
    bars = [
        {"time": ts("09:30"), "open": 100, "high": 110, "low": 99, "close": 100},
        {"time": ts("09:33"), "open": 100, "high": 105, "low": 97, "close": 101},
    ]
    add_outcomes(rows, bars)
    assert rows[0]["outcome"]["label"] == "Target / invalidation order unknown"
    assert rows[0]["outcome"]["target_time"] == ts("09:33")
    add_outcomes(rows, [])
    assert rows[0]["outcome"]["label"] == "Outcome unavailable"


def trace_block(name: str, when: str, reason: str, decision: str = "wait") -> str:
    response = json.dumps(
        {
            "decision": decision,
            "reasoning": reason,
            "case_for": "Support holds",
            "case_against": "Volume fades",
        }
    )
    return f"""### Tick #12 | entry_timing:{name} | {when}:00 | 5000ms
**Model**: `{name}-model`
<details>
<summary>System prompt (30 chars)</summary>
```
{{"reasoning": "Fake prompt response"}}
```
</details>
<details>
<summary>Human message (40 chars)</summary>
```
## Triggered Scenario
Label: Support reclaim
```
</details>
**Response**:
```
{response}
```
"""


def test_agent_answers_are_paired_and_linked_to_actual_consensus(tmp_path: Path) -> None:
    path = tmp_path / "trace.md"
    path.write_text(
        trace_block("opus", "09:36", "Hold support", "enter_now")
        + trace_block("astra", "09:36", "Wait volume")
    )
    decisions = read_decisions(path, tmp_path, "2026-09-24", [])
    assert len(decisions) == 1
    assert decisions[0]["agents"]["opus"]["reasoning"] == "Hold support"
    rows = scenarios(
        [
            scenario_event("created", "09:29"),
            scenario_event(
                "entry_timing",
                "09:35",
                decision="wait",
                reasoning="opus: Hold support | astra: Wait volume",
            ),
        ]
    )
    link_decisions(decisions, rows)
    assert len(decisions) == 1
    assert decisions[0]["scenario_id"] == rows[0]["id"]
    assert decisions[0]["consensus"] == "wait"
    assert decisions[0]["time"] == ts("09:35")
    assert len(decisions[0]["agents"]) == 2


def test_missing_agent_and_repeated_tick_after_restart_remain_separate(tmp_path: Path) -> None:
    path = tmp_path / "trace.md"
    path.write_text(
        trace_block("opus", "09:36", "First")
        + trace_block("opus", "10:10", "Restart")
        + trace_block("astra", "10:10", "Second")
    )
    decisions = read_decisions(path, tmp_path, "2026-09-24", [])
    assert len(decisions) == 2
    assert list(decisions[0]["agents"]) == ["opus"]
    assert len(decisions[1]["agents"]) == 2


def test_consensus_without_agent_trace_is_still_reviewable() -> None:
    rows = scenarios(
        [
            scenario_event("created", "09:29"),
            scenario_event("entry_timing", "09:35", decision="pass", reasoning="Pre-check pass"),
        ]
    )
    decisions = []
    link_decisions(decisions, rows)
    assert decisions[0]["agents"] == {}
    assert decisions[0]["consensus"] == "pass"
    assert decisions[0]["recorded_reasoning"] == "Pre-check pass"
