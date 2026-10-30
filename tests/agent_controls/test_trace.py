from datetime import datetime
from pathlib import Path

import pytest

from agent_controls import trace


@pytest.fixture(autouse=True)
def reset_trace_state(monkeypatch):
    monkeypatch.setattr(trace, "_trace_dir", None)
    monkeypatch.setattr(trace, "_current_date", None)
    monkeypatch.setattr(trace, "_tick_counter", 0)
    monkeypatch.setattr(trace, "_session_usage", trace.TokenUsage())
    monkeypatch.setattr(trace, "_usage_date", None)


USAGE = {"input_tokens": 1000, "output_tokens": 50, "input_token_details": {"cache_read": 800}}


def _trace_files(tmp_path):
    return sorted(tmp_path.glob("trace_*.md"))


def test_token_usage_records_calls_and_cache_reads():
    usage = trace.TokenUsage()
    usage.record(USAGE)
    usage.record_skip()
    assert usage.total_tokens == 1050
    assert usage.effective_input_tokens == 200 + 80
    assert usage.llm_calls == 1
    assert usage.skipped_calls == 1
    assert "1 made, 1 skipped" in usage.summary()


def test_new_tick_increments_counter():
    assert trace.new_tick() == 1
    assert trace.new_tick() == 2


def test_llm_call_without_trace_dir_still_counts_tokens(tmp_path):
    trace.trace_llm_call("analyze", "ANALYZE", {"a": 1}, "{}", {"ok": True}, usage_metadata=USAGE)
    assert trace.get_session_usage().llm_calls == 1
    assert _trace_files(tmp_path) == []


def test_llm_call_writes_header_once_and_entries(tmp_path):
    trace.init(str(tmp_path))
    trace.new_tick()
    trace.trace_llm_call("analyze", "ANALYZE", {"price": 1}, "raw", {"ok": True}, 12, None, USAGE)
    trace.trace_llm_call("decide", "DECIDE", {}, "not json", None, error="parse error")
    [path] = _trace_files(tmp_path)
    text = path.read_text()
    assert text.count("# LLM Trace: ") == 1
    assert "### Tick #1 | analyze" in text
    assert "1,000 in (800 cached) / 50 out" in text
    assert "**Parsed result** (decide): `null` (parse failed)" in text
    assert "**ERROR**: parse error" in text


def test_deterministic_node_is_traced(tmp_path):
    trace.init(str(tmp_path))
    trace.new_tick()
    trace.trace_deterministic("execute_trade", {"action": "HOLD"}, {"submitted": False})
    [path] = _trace_files(tmp_path)
    text = path.read_text()
    assert "| execute_trade |" in text
    assert "deterministic" in text
    assert '"submitted": false' in text


APPS = Path(__file__).resolve().parents[2] / "apps"
DAY = "2026-01-07"
ENTRY_HUMAN = "Label: Opening range breakout\nPrice: 512.40"
ENTRY_RESPONSE = '{"decision": "enter", "reasoning": "Range held on volume.", "verdict": "go"}'


def _write_entry_timing_trace(tmp_path, monkeypatch) -> Path:
    """Write one entry-timing pair and one deterministic node with the core writer."""
    monkeypatch.setattr(trace, "datetime", _FixedClock)
    trace.init(str(tmp_path))
    trace.new_tick()
    for agent in ("opus", "astra"):
        trace.trace_llm_call(
            f"entry_timing:{agent}",
            "ENTRY_TIMING",
            ENTRY_HUMAN,
            ENTRY_RESPONSE,
            {"decision": "enter"},
            duration_ms=1500,
            model=f"model-{agent}",
        )
    trace.trace_deterministic("execute_trade", {"action": "BUY"}, {"submitted": True})
    return tmp_path / f"trace_{DAY}.md"


class _FixedClock(datetime):
    @classmethod
    def now(cls, tz=None):
        return cls(2026, 1, 7, 10, 49, 21)


def test_claude_review_parser_reads_writer_output(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(APPS / "claude-review-app"))
    from claude_review.trace_parser import parse_leg_response, parse_trace

    path = _write_entry_timing_trace(tmp_path, monkeypatch)
    entries = parse_trace(path)

    assert [entry.kind for entry in entries] == [
        "entry_timing:opus",
        "entry_timing:astra",
        "execute_trade",
    ]
    opus = entries[0]
    assert (opus.model, opus.latency_ms, opus.time_text) == ("model-opus", 1500, "10:49:21")
    assert opus.human_message == ENTRY_HUMAN
    assert opus.response == ENTRY_RESPONSE
    assert entries[1].parsed == {"decision": "enter"}
    leg = parse_leg_response(opus.response, opus.model, opus.latency_ms)
    assert (leg["decision"], leg["verdict"]) == ("enter", "go")


def test_codex_review_reader_reads_writer_output(tmp_path, monkeypatch):
    monkeypatch.syspath_prepend(str(APPS / "codex-review-app" / "backend"))
    from review_app.reasoning import read_decisions

    path = _write_entry_timing_trace(tmp_path, monkeypatch)
    warnings: list[str] = []
    [decision] = read_decisions(path, tmp_path, DAY, warnings)

    assert warnings == []
    assert decision["label"] == "Opening range breakout"
    assert set(decision["agents"]) == {"opus", "astra"}
    opus = decision["agents"]["opus"]
    assert (opus["model"], opus["decision"], opus["verdict"]) == ("model-opus", "enter", "go")
    assert opus["raw"] == ENTRY_RESPONSE
