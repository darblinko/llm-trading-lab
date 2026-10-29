"""Parse the daily LLM trace Markdown written by the trading agent.

An entry starts at a line of the exact form `### Tick #N | <kind> | HH:MM:SS | <n>ms`.
EXIT SIGNAL and EXIT FILL events omit the latency part. Prompt bodies carry their
own `### ` headings, so only a line matching the full header pattern starts an entry.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any, TextIO

from claude_review.payload_types import AgentLeg

logger = logging.getLogger(__name__)

HEADER_PATTERN = re.compile(r"^### Tick #(\d+) \| (.+) \| (\d{2}:\d{2}:\d{2})(?: \| (\d+)ms)?$")
MODEL_PREFIX = "**Model**: "
SUMMARY_SECTIONS = (("<summary>System prompt (", "system"), ("<summary>Human message (", "human"))
DETAILS_CLOSE = "</details>"
RESPONSE_MARKER = "**Response**:"
PARSED_PREFIX = "**Parsed result** ("
PARSED_NULL_SUFFIX = "`null` (parse failed)"
FENCE = "```"
ENTRY_SEPARATOR = "---"
UNPARSED_DECISION = "unparsed"
LEG_KEYS = frozenset(
    {"decision", "reasoning", "key_factors", "case_for", "case_against", "verdict", "wait_for"}
)


@dataclass(frozen=True)
class TraceEntry:
    """One trace entry: an LLM call, or an exit event with empty call fields."""

    tick: int
    kind: str
    time_text: str
    latency_ms: int | None
    model: str
    human_message: str
    response: str
    parsed: dict[str, Any] | None


def parse_trace(path: Path) -> list[TraceEntry]:
    """Return every entry of a trace file in file order; a missing file gives []."""
    if not path.exists():
        return []
    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            return [
                _build_entry(header, body)
                for header, body in _entry_blocks(_complete_lines(handle))
            ]
    except OSError as exc:
        logger.error("Could not read trace file %s: %s", path, exc)
        return []


def _complete_lines(handle: TextIO) -> Iterator[str]:
    """Yield lines without their newline, skipping a final line the writer has not finished."""
    for line in handle:
        if line.endswith("\n"):
            yield line[:-1]


def _entry_blocks(lines: Iterable[str]) -> Iterator[tuple[re.Match[str], list[str]]]:
    """Group lines into (header match, body lines) per entry; text before any header is dropped."""
    header: re.Match[str] | None = None
    body: list[str] = []
    for line in lines:
        match = HEADER_PATTERN.match(line)
        if match is None:
            body.append(line)
            continue
        if header is not None:
            yield header, body
        header, body = match, []
    if header is not None:
        yield header, body


def _build_entry(header: re.Match[str], body: list[str]) -> TraceEntry:
    sections = _split_sections(_drop_trailing_separator(body))
    latency = header.group(4)
    return TraceEntry(
        tick=int(header.group(1)),
        kind=header.group(2).strip(),
        time_text=header.group(3),
        latency_ms=int(latency) if latency is not None else None,
        model=_model_name(sections["head"]),
        human_message=_unfence(sections["human"]),
        response=_unfence(sections["response"]),
        parsed=_parse_parsed_block(sections["parsed"]),
    )


def _drop_trailing_separator(lines: list[str]) -> list[str]:
    """Remove the `---` line and blanks that the tracer writes before the next header."""
    body = _strip_blank_edges(lines)
    if body and body[-1] == ENTRY_SEPARATOR:
        return _strip_blank_edges(body[:-1])
    return body


def _split_sections(lines: list[str]) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "head": [],
        "system": [],
        "human": [],
        "response": [],
        "parsed": [],
    }
    state = "head"
    for line in lines:
        state, is_content = _next_state(state, line)
        if is_content:
            sections[state].append(line)
    return sections


def _next_state(state: str, line: str) -> tuple[str, bool]:
    """Return the section a line belongs to and whether it is section content."""
    if state in ("system", "human"):
        if line == DETAILS_CLOSE:
            return "head", False
        return state, True
    if line.startswith(PARSED_PREFIX):
        return "parsed", True
    if state == "head":
        for prefix, section in SUMMARY_SECTIONS:
            if line.startswith(prefix):
                return section, False
        if line == RESPONSE_MARKER:
            return "response", False
    return state, True


def _strip_blank_edges(lines: list[str]) -> list[str]:
    start, end = 0, len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]


def _unfence(lines: list[str]) -> str:
    """Join a block body, dropping only the tracer's own opening and closing fence lines."""
    body = _strip_blank_edges(lines)
    if body and body[0].startswith(FENCE):
        body = body[1:]
    if body and body[-1] == FENCE:
        body = body[:-1]
    return "\n".join(body)


def _model_name(head: list[str]) -> str:
    for line in head:
        if line.startswith(MODEL_PREFIX):
            return line[len(MODEL_PREFIX) :].strip().strip("`")
    return ""


def _parse_parsed_block(lines: list[str]) -> dict[str, Any] | None:
    """Decode the last `**Parsed result**` block; a null marker or bad JSON gives None."""
    markers = [index for index, line in enumerate(lines) if line.startswith(PARSED_PREFIX)]
    if not markers or lines[markers[-1]].endswith(PARSED_NULL_SUFFIX):
        return None
    marker = lines[markers[-1]]
    try:
        value = json.loads(_unfence(lines[markers[-1] + 1 :]))
    except json.JSONDecodeError as exc:
        logger.warning("Unreadable trace block %r: %s", marker, exc)
        return None
    if not isinstance(value, dict):
        logger.warning("Trace block %r holds %s, not an object", marker, type(value).__name__)
        return None
    return value


def parse_leg_response(raw: str, model: str, latency_ms: int | None) -> AgentLeg:
    """Turn one agent's verbatim response into an AgentLeg; text without JSON is 'unparsed'."""
    data = _find_json_object(raw)
    if data is None:
        logger.warning(
            "Response from %s holds no JSON object; showing raw text (%d chars)", model, len(raw)
        )
        data = {"decision": UNPARSED_DECISION, "reasoning": raw}
    return AgentLeg(
        model=model,
        decision=_as_text(data.get("decision")).strip().lower(),
        reasoning=_as_text(data.get("reasoning")),
        key_factors=_as_text_list(data.get("key_factors")),
        case_for=_as_text(data.get("case_for")),
        case_against=_as_text(data.get("case_against")),
        verdict=_as_text(data.get("verdict")),
        wait_for=_as_text(data.get("wait_for")),
        latency_ms=latency_ms,
        raw_response=raw,
    )


def _find_json_object(raw: str) -> dict[str, Any] | None:
    """Return the first JSON object with a leg field, allowing code fences and surrounding prose."""
    text = "\n".join(line for line in raw.splitlines() if not line.strip().startswith(FENCE))
    decoder = json.JSONDecoder()
    for start in (index for index, char in enumerate(text) if char == "{"):
        try:
            value, _ = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict) and LEG_KEYS & value.keys():
            return value
    return None


def _as_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    return json.dumps(value)


def _as_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        return [_as_text(item) for item in value if item is not None]
    text = _as_text(value)
    return [text] if text else []
