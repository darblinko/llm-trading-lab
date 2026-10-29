"""Tests for claude_review.evaluations, using synthetic scenario rows and trace entries."""

import json
from typing import Any

from claude_review.chart_time import to_chart_time
from claude_review.evaluations import build_evaluations
from claude_review.trace_parser import TraceEntry

SESSION = "2026-09-24"


def row(time_text: str, label: str, decision: str = "wait", **fields: str) -> dict[str, Any]:
    """Build a scenarios-log entry_timing row with an ET offset timestamp."""
    return {
        "event_timestamp": f"{SESSION}T{time_text}.926053-04:00",
        "status": "entry_timing",
        "label": label,
        "decision": decision,
        "reasoning": fields.get(
            "reasoning", f"No consensus (opus={decision}, astra={decision}). opus: r1 | astra: r2"
        ),
        "bull_case": fields.get("bull_case", ""),
        "bear_case": fields.get("bear_case", ""),
        "verdict": fields.get("verdict", ""),
    }


def leg_entry(
    leg: str, time_text: str, label: str, decision: str, parsed: dict[str, Any] | None = None
) -> TraceEntry:
    return TraceEntry(
        tick=45,
        kind=f"entry_timing:{leg}",
        time_text=time_text,
        latency_ms=30000,
        model=f"model-{leg}",
        human_message=f"## Triggered Scenario\nLabel: {label}\nDirection: put",
        response=json.dumps({"decision": decision, "reasoning": f"{leg} says {decision}"}),
        parsed=parsed,
    )


def pair(time_text: str, label: str, decision: str = "wait") -> list[TraceEntry]:
    consensus = {
        "decision": decision,
        "ballot": {"opus": decision, "astra": decision},
        "reasoning": "short",
    }
    return [
        leg_entry("opus", time_text, label, decision),
        leg_entry("astra", time_text, label, decision, parsed=consensus),
    ]


def chart(time_text: str) -> int:
    return to_chart_time(f"{SESSION}T{time_text}")


def no_scenario(label: str, when: int) -> str | None:
    return None


def test_exact_link_uses_trace_legs() -> None:
    [evaluation] = build_evaluations(
        [row("11:55:50", "Fade")], pair("11:56:29", "Fade"), SESSION, no_scenario
    )

    assert evaluation["id"] == "eval@11:55:50"
    assert evaluation["time"] == chart("11:55:50")
    assert evaluation["link_quality"] == "exact"
    assert evaluation["note"] is None
    assert set(evaluation["legs"]) == {"opus", "astra"}
    assert evaluation["legs"]["opus"]["reasoning"] == "opus says wait"
    assert evaluation["legs"]["astra"]["model"] == "model-astra"
    assert evaluation["legs"]["astra"]["latency_ms"] == 30000


def test_row_fields_are_copied() -> None:
    source = row(
        "11:10:50",
        "Breakdown",
        "enter_now",
        reasoning="Unanimous enter (opus=enter_now, astra=enter_now). opus: a | astra: b",
    )

    [evaluation] = build_evaluations([source], [], SESSION, no_scenario)

    assert (evaluation["label"], evaluation["decision"]) == ("Breakdown", "enter_now")
    assert evaluation["consensus_reasoning"] == source["reasoning"]


def test_two_pairs_in_window_is_ambiguous_and_links_earliest() -> None:
    entries = pair("11:56:29", "Fade", "wait") + pair("11:59:00", "Fade", "pass")

    evaluation, leftover = build_evaluations(
        [row("11:55:50", "Fade")], entries, SESSION, no_scenario
    )

    assert evaluation["link_quality"] == "ambiguous"
    assert evaluation["legs"]["opus"]["reasoning"] == "opus says wait"
    assert "earliest" in evaluation["note"]
    assert (leftover["link_quality"], leftover["decision"]) == ("trace_only", "pass")


def test_repeat_evaluations_of_one_label_link_exactly() -> None:
    rows = [row("15:16:12", "Breakout", "wait"), row("15:19:18", "Breakout", "pass")]
    entries = pair("15:16:47", "Breakout", "wait") + pair("15:19:41", "Breakout", "pass")

    first, second = build_evaluations(rows, entries, SESSION, no_scenario)

    assert [first["link_quality"], second["link_quality"]] == ["exact", "exact"]
    assert first["legs"]["opus"]["decision"] == "wait"
    assert second["legs"]["opus"]["decision"] == "pass"


def test_same_tick_rows_link_by_label() -> None:
    rows = [row("12:00:00", "Call A"), row("12:00:00", "Put B")]
    entries = pair("12:00:35", "Call A", "wait") + pair("12:01:10", "Put B", "pass")

    evaluations = build_evaluations(rows, entries, SESSION, no_scenario)

    assert [e["id"] for e in evaluations] == ["eval@12:00:00", "eval@12:00:00-2"]
    by_label = {e["label"]: e for e in evaluations}
    assert by_label["Call A"]["legs"]["opus"]["decision"] == "wait"
    assert by_label["Put B"]["legs"]["opus"]["decision"] == "pass"
    assert {e["link_quality"] for e in evaluations} == {"exact"}


def test_pair_outside_window_is_not_linked() -> None:
    source = row(
        "11:00:00", "Fade", reasoning="No consensus (opus=wait, astra=wait). opus: r1 | astra: r2"
    )

    evaluations = build_evaluations([source], pair("11:05:01", "Fade"), SESSION, no_scenario)

    assert [e["link_quality"] for e in evaluations] == ["reconstructed", "trace_only"]


def test_pair_with_other_label_is_not_linked() -> None:
    evaluations = build_evaluations(
        [row("11:00:00", "Fade")], pair("11:00:30", "Other"), SESSION, no_scenario
    )

    assert [e["link_quality"] for e in evaluations] == ["reconstructed", "trace_only"]


def test_reconstructed_legs_split_the_row_text() -> None:
    source = row(
        "12:31:57",
        "Gap fill",
        "wait",
        reasoning=(
            "No consensus (opus=wait, astra=pass). opus: Fading momentum | astra: No structure"
        ),
        bull_case="opus: momentum slowing | astra: oscillator turned down",
        bear_case="astra: volume light",
        verdict="No consensus (opus=wait, astra=pass). opus: Against wins | astra: Pass now",
    )

    [evaluation] = build_evaluations([source], [], SESSION, no_scenario)

    assert evaluation["link_quality"] == "reconstructed"
    assert "scenarios log" in evaluation["note"]
    opus, astra = evaluation["legs"]["opus"], evaluation["legs"]["astra"]
    assert (opus["decision"], opus["reasoning"], opus["case_for"]) == (
        "wait",
        "Fading momentum",
        "momentum slowing",
    )
    assert (opus["case_against"], opus["verdict"], opus["raw_response"]) == ("", "Against wins", "")
    assert (astra["decision"], astra["case_against"], astra["verdict"]) == (
        "pass",
        "volume light",
        "Pass now",
    )
    assert astra["latency_ms"] is None


def test_pre_check_row_is_missing_trace() -> None:
    source = row(
        "11:55:57", "Reclaim call", "pass", reasoning="Pre-check: pass before any model call"
    )

    [evaluation] = build_evaluations([source], [], SESSION, no_scenario)

    assert evaluation["link_quality"] == "missing_trace"
    assert evaluation["legs"] == {"opus": None, "astra": None}
    assert "before any model call" in evaluation["note"]


def test_unmatched_pair_becomes_trace_only() -> None:
    [evaluation] = build_evaluations([], pair("13:00:08", "Bounce", "pass"), SESSION, no_scenario)

    assert evaluation["id"] == "eval@13:00:08"
    assert evaluation["time"] == chart("13:00:08")
    assert (evaluation["label"], evaluation["decision"]) == ("Bounce", "pass")
    assert evaluation["consensus_reasoning"] == "short"
    assert evaluation["link_quality"] == "trace_only"
    assert evaluation["legs"]["astra"]["decision"] == "pass"


def test_trace_only_without_consensus_block_is_unknown() -> None:
    entries = [
        leg_entry("opus", "13:00:08", "Bounce", "pass"),
        leg_entry("astra", "13:00:08", "Bounce", "pass"),
    ]

    [evaluation] = build_evaluations([], entries, SESSION, no_scenario)

    assert evaluation["decision"] == "unknown"
    assert evaluation["consensus_reasoning"] == ""


def test_resolver_receives_label_and_chart_time() -> None:
    calls: list[tuple[str, int]] = []

    def resolve(label: str, when: int) -> str | None:
        calls.append((label, when))
        return f"scn-{label}"

    [evaluation] = build_evaluations(
        [row("11:55:50", "Fade")], pair("11:56:29", "Fade"), SESSION, resolve
    )

    assert calls == [("Fade", chart("11:55:50"))]
    assert evaluation["scenario_id"] == "scn-Fade"


def test_non_entry_timing_trace_entries_are_ignored() -> None:
    thesis = TraceEntry(0, "thesis_refresh", "11:56:00", 90000, "m", "Label: Fade", "{}", None)
    exit_fill = TraceEntry(140, "EXIT FILL: stop_loss", "11:56:10", None, "", "", "", None)

    evaluations = build_evaluations([], [thesis, exit_fill], SESSION, no_scenario)

    assert evaluations == []


def test_row_without_timestamp_is_skipped() -> None:
    broken = {**row("11:55:50", "Fade"), "event_timestamp": None}

    assert build_evaluations([broken], [], SESSION, no_scenario) == []


def test_output_is_sorted_by_time() -> None:
    rows = [row("14:00:00", "Late"), row("10:00:00", "Early")]

    evaluations = build_evaluations(rows, pair("12:00:00", "Middle"), SESSION, no_scenario)

    assert [e["label"] for e in evaluations] == ["Early", "Middle", "Late"]
