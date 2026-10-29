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
    assert "PARSE FAILED" in text
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
