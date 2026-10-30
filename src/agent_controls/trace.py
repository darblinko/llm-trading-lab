"""Lightweight LLM call tracing for human-readable debugging.

Writes a daily markdown trace file with the full context sent to and
received from each LLM node.  Each tick gets a timestamped section
showing the human message, raw response, and parsed result.

Usage:
    from agent_controls.trace import trace_llm_call

    trace_llm_call(
        node="analyze_market",
        system_prompt_name="ANALYZE_MARKET",
        payload=payload_dict,
        raw_response=response.content,
        parsed_result=parsed_dict,
        duration_ms=elapsed,
        model="model-name",
    )

Entry schema, shared with the review apps under apps/ (their trace readers
are tested against this writer in tests/agent_controls/test_trace.py):

    ### Tick #N | <node> | HH:MM:SS | <n>ms
    **Model**: `<model>`
    <details> <summary>Human message (<n> chars)</summary> fenced text </details>
    **Response**: fenced raw response
    **Parsed result** (<node>): fenced JSON, or `null` (parse failed)

Deterministic entries use the header without the latency part. The review
apps select entry-timing calls by node name (`entry_timing:opus`,
`entry_timing:astra`) and read the setup from a `Label: ...` line in the
human message; pass `payload` as a string to control that text.
"""

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime

logger = logging.getLogger(__name__)

_trace_dir: str | None = None
_current_date: str | None = None
_tick_counter: int = 0


# ---------------------------------------------------------------------------
# Cumulative token counter
# ---------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Cumulative token usage for the current session."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_creation_tokens: int = 0
    llm_calls: int = 0
    skipped_calls: int = 0  # calls avoided by gate/floor/decision-skip

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    @property
    def effective_input_tokens(self) -> int:
        """Input tokens at effective cost (cache reads at 10% cost)."""
        non_cached = self.input_tokens - self.cache_read_tokens
        return non_cached + int(self.cache_read_tokens * 0.1)

    def record(self, usage_metadata: dict) -> None:
        """Record token usage from a LangChain response."""
        self.input_tokens += usage_metadata.get("input_tokens", 0)
        self.output_tokens += usage_metadata.get("output_tokens", 0)
        details = usage_metadata.get("input_token_details", {})
        self.cache_read_tokens += details.get("cache_read", 0)
        self.cache_creation_tokens += details.get("cache_creation", 0)
        self.llm_calls += 1

    def record_skip(self) -> None:
        """Record a skipped LLM call (gate/floor/decision-skip)."""
        self.skipped_calls += 1

    def summary(self) -> str:
        """One-line summary for logging."""
        return (
            f"tokens: {self.total_tokens:,} total "
            f"({self.input_tokens:,} in / {self.output_tokens:,} out / "
            f"{self.cache_read_tokens:,} cached) | "
            f"calls: {self.llm_calls} made, {self.skipped_calls} skipped"
        )


# Module-level singleton, reset daily
_session_usage = TokenUsage()
_usage_date: str | None = None


def get_session_usage() -> TokenUsage:
    """Return the current session's cumulative token usage."""
    global _session_usage, _usage_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _usage_date != today:
        _session_usage = TokenUsage()
        _usage_date = today
    return _session_usage


def init(trace_dir: str) -> None:
    """Set the directory for trace files."""
    global _trace_dir
    _trace_dir = trace_dir
    os.makedirs(trace_dir, exist_ok=True)


def new_tick() -> int:
    """Increment and return the tick counter. Call once at the start of each tick."""
    global _tick_counter, _current_date
    today = datetime.now().strftime("%Y-%m-%d")
    if _current_date != today:
        _current_date = today
        _tick_counter = 0
    _tick_counter += 1
    return _tick_counter


def trace_llm_call(
    node: str,
    system_prompt_name: str,
    payload: dict | str,
    raw_response: str,
    parsed_result: dict | None,
    duration_ms: int = 0,
    error: str | None = None,
    usage_metadata: dict | None = None,
    model: str = "",
) -> None:
    """Write a single LLM call trace entry to the daily markdown file.

    Args:
        node: Node name (e.g., "analyze_market", "make_decision", "premarket").
        system_prompt_name: Name of the system prompt used (e.g., "ANALYZE_MARKET").
        payload: The HumanMessage content: a dict is written as JSON, a string verbatim.
        raw_response: The raw text response from the LLM.
        parsed_result: The parsed JSON dict (or None if parse failed).
        duration_ms: Time taken for the LLM call in milliseconds.
        error: Error message if parsing failed.
        usage_metadata: Token usage dict from response.usage_metadata.
        model: Model name written to the **Model** line; empty omits the line.
    """
    # Record tokens in cumulative counter
    usage = get_session_usage()
    if usage_metadata:
        usage.record(usage_metadata)

    if _trace_dir is None:
        return

    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(_trace_dir, f"trace_{today}.md")
    now = datetime.now().strftime("%H:%M:%S")

    payload_str = (
        payload if isinstance(payload, str) else json.dumps(payload, indent=2, default=str)
    )
    parsed_block = (
        f"**Parsed result** ({node}):\n```json\n"
        f"{json.dumps(parsed_result, indent=2, default=str)}\n```"
        if parsed_result
        else f"**Parsed result** ({node}): `null` (parse failed)"
    )
    model_line = f"**Model**: `{model}`\n\n" if model else ""
    error_line = f"**ERROR**: {error}\n\n" if error else ""

    # Token usage line
    token_line = ""
    if usage_metadata:
        inp = usage_metadata.get("input_tokens", 0)
        out = usage_metadata.get("output_tokens", 0)
        details = usage_metadata.get("input_token_details", {})
        cached = details.get("cache_read", 0)
        token_line = (
            f"\n**Tokens**: {inp:,} in ({cached:,} cached) / {out:,} out"
            f" | **Session total**: {usage.total_tokens:,}\n"
        )

    entry = f"""
---

### Tick #{_tick_counter} | {node} | {now} | {duration_ms}ms

{model_line}**Prompt**: `{system_prompt_name}`
{token_line}
{error_line}<details>
<summary>Human message ({len(payload_str)} chars)</summary>

```
{payload_str}
```
</details>

**Response**:
```
{raw_response}
```

{parsed_block}

"""

    try:
        with open(path, "a") as f:
            if f.tell() == 0:
                f.write(f"# LLM Trace: {today}\n\n")
            f.write(entry)
    except Exception as exc:
        logger.warning("Failed to write trace: %s", exc)


def trace_deterministic(
    node: str,
    inputs: dict,
    result: dict,
) -> None:
    """Trace a deterministic (non-LLM) node execution.

    Args:
        node: Node name (e.g., "execute_trade").
        inputs: Key inputs to the node.
        result: The node's output.
    """
    if _trace_dir is None:
        return

    today = datetime.now().strftime("%Y-%m-%d")
    path = os.path.join(_trace_dir, f"trace_{today}.md")
    now = datetime.now().strftime("%H:%M:%S")

    inputs_str = json.dumps(inputs, indent=2, default=str)
    result_str = json.dumps(result, indent=2, default=str)

    entry = f"""
---

### Tick #{_tick_counter} | {node} | {now}

No LLM call: deterministic node.

**Inputs**:
```json
{inputs_str}
```

**Result**:
```json
{result_str}
```

"""

    try:
        with open(path, "a") as f:
            f.write(entry)
    except Exception as exc:
        logger.warning("Failed to write trace: %s", exc)
