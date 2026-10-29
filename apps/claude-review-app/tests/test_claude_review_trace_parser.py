"""Tests for claude_review.trace_parser, using synthetic trace text in the tracer's format."""

import json
from pathlib import Path

from claude_review.trace_parser import TraceEntry, parse_leg_response, parse_trace

SYSTEM_PROMPT = """### 1. Section heading
**Response**:
### Tick #99 | not a header
Rules text."""

HUMAN_MESSAGE = """## Triggered Scenario
Label: VWAP reclaim call
Direction: call"""

OPUS_JSON = json.dumps({"decision": "wait", "reasoning": "Momentum fading", "wait_for": None})


def llm_entry(tick: int, kind: str, time_text: str, latency: int, response: str) -> str:
    """Render one LLM call exactly as the trading agent's tracer writes it."""
    return f"""
---

### Tick #{tick} | {kind} | {time_text} | {latency}ms

**Model**: `model-{kind}`

<details>
<summary>System prompt ({len(SYSTEM_PROMPT)} chars)</summary>

```
{SYSTEM_PROMPT}
```

</details>

<details>
<summary>Human message ({len(HUMAN_MESSAGE)} chars)</summary>

```
{HUMAN_MESSAGE}
```

</details>

**Response**:
```
{response}
```

"""


def parsed_block(label: str, parsed: dict | None) -> str:
    """Render a block exactly as the tracer writes it."""
    if parsed is None:
        return f"\n**Parsed result** ({label}): `null` (parse failed)\n"
    return f"\n**Parsed result** ({label}):\n```json\n{json.dumps(parsed, indent=2)}\n```\n"


def exit_event(tick: int, header: str, time_text: str) -> str:
    """Render a non-LLM event exactly as the tracer writes it."""
    lines = [
        "\n---\n",
        f"### Tick #{tick} | {header} | {time_text}\n",
        "**Symbol**: `QQQ260924C00740000`",
        '\n**Context**:\n```json\n{\n  "qty": 1\n}\n```',
    ]
    return "\n".join(lines) + "\n"


def write_trace(tmp_path: Path, *parts: str) -> Path:
    path = tmp_path / "trace_2026-09-24.md"
    path.write_text("# LLM Trace 2026-09-24\n\n" + "".join(parts), encoding="utf-8")
    return path


def test_missing_file_returns_empty_list(tmp_path: Path) -> None:
    assert parse_trace(tmp_path / "trace_2026-01-01.md") == []


def test_parses_llm_entry_fields(tmp_path: Path) -> None:
    path = write_trace(tmp_path, llm_entry(45, "entry_timing:opus", "11:11:27", 14480, OPUS_JSON))

    [entry] = parse_trace(path)

    assert entry == TraceEntry(
        tick=45,
        kind="entry_timing:opus",
        time_text="11:11:27",
        latency_ms=14480,
        model="model-entry_timing:opus",
        human_message=HUMAN_MESSAGE,
        response=OPUS_JSON,
        parsed=None,
    )


def test_prompt_headings_and_markers_do_not_split_entries(tmp_path: Path) -> None:
    path = write_trace(
        tmp_path,
        llm_entry(45, "entry_timing:opus", "11:11:27", 14480, OPUS_JSON),
        llm_entry(45, "entry_timing:astra", "11:11:27", 35688, "{}"),
    )

    entries = parse_trace(path)

    assert [entry.kind for entry in entries] == ["entry_timing:opus", "entry_timing:astra"]
    assert entries[0].response == OPUS_JSON


def test_parsed_result_attaches_to_preceding_entry(tmp_path: Path) -> None:
    consensus = {
        "decision": "wait",
        "ballot": {"opus": "wait", "astra": "wait"},
        "reasoning": "No consensus",
    }
    path = write_trace(
        tmp_path,
        llm_entry(45, "entry_timing:opus", "11:11:27", 14480, OPUS_JSON),
        llm_entry(45, "entry_timing:astra", "11:11:27", 35688, "{}"),
        parsed_block("entry_timing_consensus", consensus),
    )

    opus, astra = parse_trace(path)

    assert opus.parsed is None
    assert astra.parsed == consensus
    assert astra.response == "{}"


def test_null_parsed_result_gives_none(tmp_path: Path) -> None:
    path = write_trace(
        tmp_path,
        llm_entry(0, "thesis_generation", "09:36:10", 90000, "not json"),
        parsed_block("thesis_generation", None),
    )

    [entry] = parse_trace(path)

    assert entry.parsed is None
    assert entry.response == "not json"


def test_exit_event_has_no_latency_model_or_response(tmp_path: Path) -> None:
    path = write_trace(
        tmp_path,
        exit_event(131, "EXIT FILL: stop_loss", "12:31:11"),
        llm_entry(143, "entry_timing:opus", "12:44:14", 32378, OPUS_JSON),
    )

    exit_entry, opus = parse_trace(path)

    assert (exit_entry.tick, exit_entry.kind, exit_entry.time_text) == (
        131,
        "EXIT FILL: stop_loss",
        "12:31:11",
    )
    assert exit_entry.latency_ms is None
    assert (exit_entry.model, exit_entry.human_message, exit_entry.response) == ("", "", "")
    assert opus.tick == 143


def test_response_with_inner_fence_is_kept_verbatim(tmp_path: Path) -> None:
    fenced = f"```json\n{OPUS_JSON}\n```"
    path = write_trace(tmp_path, llm_entry(45, "entry_timing:opus", "11:11:27", 14480, fenced))

    [entry] = parse_trace(path)

    assert entry.response == fenced


def test_truncated_final_entry_is_tolerated(tmp_path: Path) -> None:
    complete = llm_entry(45, "entry_timing:opus", "11:11:27", 14480, OPUS_JSON)
    partial = llm_entry(
        45, "entry_timing:astra", "11:11:27", 35688, '{\n"decision": "wait",\n"reasoning": "cut'
    )
    cut_at = partial.index('"reasoning"') + len('"reasoning": "cu')
    path = write_trace(tmp_path, complete, partial[:cut_at])

    opus, astra = parse_trace(path)

    assert opus.response == OPUS_JSON
    assert astra.kind == "entry_timing:astra"
    assert astra.response == '{\n"decision": "wait",'


def test_leg_from_plain_json() -> None:
    raw = json.dumps(
        {
            "decision": "Enter_Now",
            "reasoning": "Structure confirmed",
            "key_factors": ["fresh cross", "MACD expanding"],
            "case_for": "for",
            "case_against": "against",
            "verdict": "for wins",
            "wait_for": None,
        }
    )

    leg = parse_leg_response(raw, "claude-opus-5-5", 14480)

    assert leg == {
        "model": "claude-opus-5-5",
        "decision": "enter_now",
        "reasoning": "Structure confirmed",
        "key_factors": ["fresh cross", "MACD expanding"],
        "case_for": "for",
        "case_against": "against",
        "verdict": "for wins",
        "wait_for": "",
        "latency_ms": 14480,
        "raw_response": raw,
    }


def test_leg_from_fenced_json() -> None:
    raw = '```json\n{"decision": "pass", "reasoning": "Zero levels lost"}\n```'

    leg = parse_leg_response(raw, "gpt-6-astra", None)

    assert (leg["decision"], leg["reasoning"]) == ("pass", "Zero levels lost")
    assert leg["raw_response"] == raw


def test_leg_from_json_embedded_in_prose() -> None:
    raw = 'Here is my {careful} answer:\n{"decision": "wait", "wait_for": "RSI > 50"}\nThanks.'

    leg = parse_leg_response(raw, "gpt-6-astra", None)

    assert (leg["decision"], leg["wait_for"]) == ("wait", "RSI > 50")


def test_leg_missing_fields_default_to_empty() -> None:
    leg = parse_leg_response('{"decision": "wait", "key_factors": null}', "m", 1)

    assert leg["key_factors"] == []
    assert (
        leg["reasoning"],
        leg["case_for"],
        leg["case_against"],
        leg["verdict"],
        leg["wait_for"],
    ) == ("",) * 5


def test_leg_timeout_payload() -> None:
    leg = parse_leg_response(
        '{"decision":"wait","reasoning":"codex timeout after 240s"}', "gpt-6-astra", 240013
    )

    assert (leg["decision"], leg["reasoning"], leg["latency_ms"]) == (
        "wait",
        "codex timeout after 240s",
        240013,
    )


def test_unparseable_leg_keeps_raw_text_as_reasoning() -> None:
    raw = "I cannot evaluate this {scenario} right now."

    leg = parse_leg_response(raw, "m", None)

    assert leg["decision"] == "unparsed"
    assert leg["reasoning"] == raw
    assert leg["key_factors"] == []
