"""Join scenarios-log entry_timing rows to the trace entries of the same consensus call.

The scenarios log is the authoritative list of consensus decisions. A row's
event_timestamp is the tick start; both legs' trace entries are stamped when the
legs return, seconds later, and up to about 250 s later when a leg times
out. Legs of one call are grouped by tick number, human message and a
LINK_WINDOW_SEC window. Trace tick numbers reset on restart, so the join to
rows uses the scenario label and time only. A call finishes inside its own tick, so a
trace pair never belongs to a row when a later row for the same label precedes it.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from typing import Any, NamedTuple

from claude_review.chart_time import to_chart_time
from claude_review.leg_reconstruction import LEG_NAMES, reconstruct_legs
from claude_review.payload_types import AgentLeg, Evaluation
from claude_review.trace_parser import TraceEntry, parse_leg_response

logger = logging.getLogger(__name__)

LINK_WINDOW_SEC = 300
ENTRY_TIMING_PREFIX = "entry_timing:"
UNKNOWN_DECISION = "unknown"
LABEL_PATTERN = re.compile(r"^Label: (.*)$", re.MULTILINE)

NOTE_RECONSTRUCTED = (
    "No trace entry matched this decision. The LLM output was reconstructed from the scenarios "
    "log, "
    "which has no key factors, wait_for or raw response."
)
NOTE_MISSING_TRACE = (
    "No LLM call was recorded for this decision, for example a pass decided before any model call, "
    "so there is no per-agent reasoning."
)
NOTE_TRACE_ONLY = (
    "No entry_timing row in the scenarios log matches this trace call. The time is the trace "
    "stamp, "
    "written after both legs returned."
)

ScenarioResolver = Callable[[str, int], str | None]
Legs = dict[str, AgentLeg | None]


class DecisionRow(NamedTuple):
    time: int
    label: str
    decision: str
    reasoning: str
    bull_case: str
    bear_case: str
    verdict: str


class TracePair(NamedTuple):
    time: int
    time_text: str
    label: str
    legs: dict[str, TraceEntry]
    consensus: dict[str, Any] | None


class Link(NamedTuple):
    pair_index: int | None
    candidate_count: int


class Draft(NamedTuple):
    time: int
    label: str
    decision: str
    consensus_reasoning: str
    legs: Legs
    link_quality: str
    note: str | None


def build_evaluations(
    entry_timing_rows: list[dict[str, Any]],
    trace_entries: list[TraceEntry],
    session_date: str,
    resolve_scenario_id: ScenarioResolver,
) -> list[Evaluation]:
    """Return one Evaluation per entry_timing row plus one per unmatched trace pair, by time."""
    rows = sorted(_decision_rows(entry_timing_rows), key=lambda row: row.time)
    pairs = _trace_pairs(trace_entries, session_date)
    links = _link_rows(rows, pairs)
    linked = {link.pair_index for link in links if link.pair_index is not None}
    drafts = [_row_draft(row, pairs, link) for row, link in zip(rows, links, strict=True)]
    drafts += [_trace_only_draft(pair) for index, pair in enumerate(pairs) if index not in linked]
    return _finalize(sorted(drafts, key=lambda draft: draft.time), resolve_scenario_id)


def _decision_rows(rows: Iterable[dict[str, Any]]) -> list[DecisionRow]:
    parsed = (_decision_row(row) for row in rows)
    return [row for row in parsed if row is not None]


def _decision_row(row: dict[str, Any]) -> DecisionRow | None:
    stamp = row.get("event_timestamp")
    try:
        if not isinstance(stamp, str) or not stamp:
            raise ValueError("event_timestamp is missing")
        time = to_chart_time(stamp)
    except ValueError as exc:
        logger.warning(
            "Skipping entry_timing row %r: bad event_timestamp %r (%s)",
            row.get("label"),
            stamp,
            exc,
        )
        return None
    return DecisionRow(
        time=time,
        label=_text(row, "label").strip(),
        decision=_text(row, "decision"),
        reasoning=_text(row, "reasoning"),
        bull_case=_text(row, "bull_case"),
        bear_case=_text(row, "bear_case"),
        verdict=_text(row, "verdict"),
    )


def _text(row: dict[str, Any], key: str) -> str:
    value = row.get(key)
    return value if isinstance(value, str) else ""


def _trace_pairs(entries: Iterable[TraceEntry], session_date: str) -> list[TracePair]:
    """Group per-leg entry_timing entries of one call.

    Legs of one call share the tick number and the human message, and each is
    stamped when it returns, so their stamps can differ by up to LINK_WINDOW_SEC.
    """
    groups: list[dict[str, TraceEntry]] = []
    for entry in entries:
        leg = _leg_name(entry.kind)
        if leg is None:
            continue
        index = next(
            (i for i in reversed(range(len(groups))) if _joins_group(groups[i], leg, entry)),
            None,
        )
        if index is None:
            groups.append({leg: entry})
        else:
            groups[index] = {**groups[index], leg: entry}
    return [_to_pair(group, session_date) for group in groups]


def _leg_name(kind: str) -> str | None:
    if not kind.startswith(ENTRY_TIMING_PREFIX):
        return None
    name = kind[len(ENTRY_TIMING_PREFIX) :].strip()
    if name not in LEG_NAMES:
        logger.warning("Ignoring trace entry for unknown entry-timing leg %r", name)
        return None
    return name


def _joins_group(group: dict[str, TraceEntry], leg: str, entry: TraceEntry) -> bool:
    first = next(iter(group.values()))
    return (
        leg not in group
        and entry.tick == first.tick
        and entry.human_message == first.human_message
        and 0
        <= _clock_seconds(entry.time_text) - _clock_seconds(first.time_text)
        <= LINK_WINDOW_SEC
    )


def _clock_seconds(time_text: str) -> int:
    hours, minutes, seconds = (int(part) for part in time_text.split(":"))
    return hours * 3600 + minutes * 60 + seconds


def _to_pair(group: dict[str, TraceEntry], session_date: str) -> TracePair:
    first = next(iter(group.values()))
    label_match = LABEL_PATTERN.search(first.human_message)
    return TracePair(
        time=to_chart_time(f"{session_date}T{first.time_text}"),
        time_text=first.time_text,
        label=label_match.group(1).strip() if label_match else "",
        legs=group,
        consensus=next(
            (entry.parsed for entry in group.values() if entry.parsed is not None), None
        ),
    )


def _link_rows(rows: list[DecisionRow], pairs: list[TracePair]) -> list[Link]:
    """Give each row, earliest first, the earliest unused same-label pair inside its window."""
    used: set[int] = set()
    links: list[Link] = []
    for index, _row in enumerate(rows):
        candidates = [i for i in _candidate_pairs(rows, index, pairs) if i not in used]
        chosen = candidates[0] if candidates else None
        if chosen is not None:
            used.add(chosen)
        links.append(Link(chosen, len(candidates)))
    return links


def _candidate_pairs(rows: list[DecisionRow], index: int, pairs: list[TracePair]) -> list[int]:
    row = rows[index]
    later_same_label = (
        later.time
        for later in rows[index + 1 :]
        if later.label == row.label and later.time > row.time
    )
    next_time = next(later_same_label, None)
    in_window = [
        i
        for i, pair in enumerate(pairs)
        if pair.label == row.label
        and row.time <= pair.time <= row.time + LINK_WINDOW_SEC
        and (next_time is None or pair.time < next_time)
    ]
    return sorted(in_window, key=lambda i: pairs[i].time)


def _row_draft(row: DecisionRow, pairs: list[TracePair], link: Link) -> Draft:
    if link.pair_index is None:
        return _unlinked_row_draft(row)
    pair = pairs[link.pair_index]
    notes = [_missing_leg_note(name) for name in LEG_NAMES if name not in pair.legs]
    if link.candidate_count > 1:
        notes.insert(0, _ambiguity_note(link.candidate_count, pair.time_text))
    quality = "ambiguous" if link.candidate_count > 1 else "exact"
    return Draft(
        row.time,
        row.label,
        row.decision,
        row.reasoning,
        _trace_legs(pair),
        quality,
        " ".join(notes) or None,
    )


def _ambiguity_note(count: int, time_text: str) -> str:
    return (
        f"{count} trace calls for this label fall within {LINK_WINDOW_SEC} s after this decision; "
        f"the earliest, stamped {time_text}, was linked."
    )


def _missing_leg_note(name: str) -> str:
    return f"The trace has no {name} leg for this call."


def _trace_legs(pair: TracePair) -> Legs:
    return {name: _leg_from_entry(pair.legs.get(name)) for name in LEG_NAMES}


def _leg_from_entry(entry: TraceEntry | None) -> AgentLeg | None:
    if entry is None:
        return None
    return parse_leg_response(entry.response, entry.model, entry.latency_ms)


def _unlinked_row_draft(row: DecisionRow) -> Draft:
    legs = reconstruct_legs(row.reasoning, row.bull_case, row.bear_case, row.verdict)
    if all(leg is None for leg in legs.values()):
        return Draft(
            row.time,
            row.label,
            row.decision,
            row.reasoning,
            legs,
            "missing_trace",
            NOTE_MISSING_TRACE,
        )
    return Draft(
        row.time, row.label, row.decision, row.reasoning, legs, "reconstructed", NOTE_RECONSTRUCTED
    )


def _trace_only_draft(pair: TracePair) -> Draft:
    consensus = pair.consensus or {}
    decision = consensus.get("decision")
    reasoning = consensus.get("reasoning")
    note = NOTE_TRACE_ONLY + (
        " The consensus reasoning is the trace's 200-character excerpt."
        if pair.consensus
        else " The trace holds no parsed consensus."
    )
    return Draft(
        pair.time,
        pair.label,
        decision if isinstance(decision, str) and decision else UNKNOWN_DECISION,
        reasoning if isinstance(reasoning, str) else "",
        _trace_legs(pair),
        "trace_only",
        note,
    )


def _finalize(drafts: list[Draft], resolve_scenario_id: ScenarioResolver) -> list[Evaluation]:
    """Assign ids of the form eval@HH:MM:SS, suffixed -2, -3 when a second repeats."""
    seen: dict[str, int] = {}
    evaluations: list[Evaluation] = []
    for draft in drafts:
        base = f"eval@{datetime.fromtimestamp(draft.time, tz=UTC).strftime('%H:%M:%S')}"
        seen[base] = seen.get(base, 0) + 1
        evaluations.append(
            Evaluation(
                id=base if seen[base] == 1 else f"{base}-{seen[base]}",
                scenario_id=resolve_scenario_id(draft.label, draft.time),
                label=draft.label,
                time=draft.time,
                decision=draft.decision,
                consensus_reasoning=draft.consensus_reasoning,
                legs=draft.legs,
                link_quality=draft.link_quality,
                note=draft.note,
            )
        )
    return evaluations
