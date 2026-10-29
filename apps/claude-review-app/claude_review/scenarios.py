"""Scenario lifecycles rebuilt from the scenarios JSONL log.

The log has no scenario ID, so rows are joined on `label` and time. Each
`created` row starts a scenario; later rows attach to the latest scenario with
that label created at or before the row. Two orderings in the trading
agent's scenario writer need care:

- A refresh runs its zone dedup before it logs its `created` rows, so a
  dedup `expired` row can precede the `created` row it belongs to by
  microseconds. Such a row attaches to a same-label scenario created within
  BATCH_GRACE after it.
- Installing a thesis replaces the whole book, so a later initial-thesis book
  (a mid-session restart) closes every earlier scenario still open.
"""

import logging
import re
from collections import Counter
from datetime import datetime, timedelta
from typing import NamedTuple

from claude_review.chart_time import to_chart_time
from claude_review.log_files import JsonRow, json_float, json_int, parse_timestamp
from claude_review.payload_types import Scenario, ScenarioEvent, Trade, TriggerZone

logger = logging.getLogger(__name__)

TERMINAL_STATUSES = frozenset({"invalidated", "expired"})
INITIAL_SOURCE = "initial_thesis"
UNLOGGED_SOURCE = "unlogged"
BOOK_NAMES = {INITIAL_SOURCE: "Initial", "thesis_refresh": "Refresh"}
# Rows written by one book install or refresh are microseconds apart.
BATCH_GRACE = timedelta(seconds=5)
REVISION_REASON = "Superseded by a new revision of this label"
RESTART_REASON = "Book replaced by a new initial thesis"
_PRICE_RULE = re.compile(r"^\s*price\s*(<=|>=|<|>)\s*(\d+(?:\.\d+)?)\s*$")


class _TimedRow(NamedTuple):
    at: datetime
    status: str
    label: str
    row: JsonRow


class _Seed(NamedTuple):
    """The row that starts a scenario: a `created` row, or the first orphan row."""

    event: _TimedRow
    source: str
    book: str
    book_start: datetime


class _Bucket(NamedTuple):
    seed: _Seed
    rows: tuple[_TimedRow, ...]


class _Closure(NamedTuple):
    at: datetime
    reason: str


def build_scenarios(rows: list[JsonRow]) -> list[Scenario]:
    """Return one Scenario per created row (plus unlogged ones), ordered by creation time."""
    timed = _timed_rows(rows)
    seeds = _created_seeds([t for t in timed if t.status == "created"])
    buckets = _assign_rows(seeds, [t for t in timed if t.status != "created"])
    closures = [_closure(bucket, buckets) for bucket in buckets]
    ids = _unique_ids(buckets)
    return [
        _scenario(bucket, scenario_id, closure)
        for bucket, scenario_id, closure in zip(buckets, ids, closures, strict=True)
    ]


def resolve_scenario_id(scenarios: list[Scenario], label: str, when: int) -> str | None:
    """Return the id of the latest scenario with `label` created at or before chart time `when`."""
    matches = [s for s in scenarios if s["label"] == label and s["created_time"] <= when]
    if not matches:
        return None
    return sorted(matches, key=lambda s: s["created_time"])[-1]["id"]


def link_trades(scenarios: list[Scenario], trades: list[Trade]) -> list[Scenario]:
    """Return a new list where scenarios a trade entered from have status "entered"."""
    entered = {_entered_scenario_id(scenarios, trade) for trade in trades}
    return [_with_status(s, "entered") if s["id"] in entered else s for s in scenarios]


def _timed_rows(rows: list[JsonRow]) -> list[_TimedRow]:
    timed: list[_TimedRow] = []
    for row in rows:
        at = parse_timestamp(row.get("event_timestamp"))
        label = row.get("label")
        if at is None or not isinstance(label, str) or not label:
            logger.warning("Skipping scenario row without timestamp or label: %.200s", row)
            continue
        timed.append(_TimedRow(at, str(row.get("status") or ""), label, row))
    return sorted(timed, key=lambda t: t.at)


def _created_seeds(created: list[_TimedRow]) -> list[_Seed]:
    """Group consecutive created rows of one source into books named by their first row."""
    seeds: list[_Seed] = []
    for event in created:
        source = str(event.row.get("source") or "")
        previous = seeds[-1] if seeds else None
        book_start = event.at
        if (
            previous is not None
            and previous.source == source
            and event.at - previous.event.at <= BATCH_GRACE
        ):
            book_start = previous.book_start
        book = f"{BOOK_NAMES.get(source, source)} {book_start:%H:%M}"
        seeds.append(_Seed(event, source, book, book_start))
    return seeds


def _assign_rows(seeds: list[_Seed], events: list[_TimedRow]) -> list[_Bucket]:
    """Attach each non-created row to its scenario, adding unlogged scenarios for orphans."""
    all_seeds = list(seeds)
    rows_by_seed: list[list[_TimedRow]] = [[] for _ in all_seeds]
    for event in events:
        index = _owner_index(all_seeds, event)
        if index is None and event.status in TERMINAL_STATUSES:
            logger.warning(
                "Dropping %s row for %r at %s: no scenario with that label was created",
                event.status,
                event.label,
                event.at.isoformat(),
            )
            continue
        if index is None:
            all_seeds.append(_Seed(event, UNLOGGED_SOURCE, "Unlogged", event.at))
            rows_by_seed.append([])
            index = len(all_seeds) - 1
        rows_by_seed[index].append(event)
    buckets = [
        _Bucket(seed, tuple(rows)) for seed, rows in zip(all_seeds, rows_by_seed, strict=True)
    ]
    return sorted(buckets, key=lambda b: b.seed.event.at)


def _owner_index(seeds: list[_Seed], event: _TimedRow) -> int | None:
    same_label = [i for i, seed in enumerate(seeds) if seed.event.label == event.label]
    earlier = [i for i in same_label if seeds[i].event.at <= event.at]
    if earlier:
        return max(earlier, key=lambda i: seeds[i].event.at)
    same_batch = [i for i in same_label if seeds[i].event.at - event.at <= BATCH_GRACE]
    return min(same_batch, key=lambda i: seeds[i].event.at) if same_batch else None


def _closure(bucket: _Bucket, buckets: list[_Bucket]) -> _Closure | None:
    """Return when an open scenario was replaced by a new revision or a new initial book."""
    if any(row.status in TERMINAL_STATUSES for row in bucket.rows):
        return None
    seed = bucket.seed
    candidates = [
        _Closure(other.seed.event.at, REVISION_REASON)
        for other in buckets
        if other.seed.event.label == seed.event.label and other.seed.event.at > seed.event.at
    ] + [
        _Closure(other.seed.book_start, RESTART_REASON)
        for other in buckets
        if other.seed.source == INITIAL_SOURCE and other.seed.book_start > seed.book_start
    ]
    return min(candidates, key=lambda c: c.at) if candidates else None


def _unique_ids(buckets: list[_Bucket]) -> list[str]:
    seen: Counter[str] = Counter()
    ids: list[str] = []
    for bucket in buckets:
        base = f"{bucket.seed.event.label}@{bucket.seed.event.at:%H:%M:%S}"
        seen[base] += 1
        ids.append(base if seen[base] == 1 else f"{base}#{seen[base]}")
    return ids


def _scenario(bucket: _Bucket, scenario_id: str, closure: _Closure | None) -> Scenario:
    seed = bucket.seed
    definition = _definition_row(bucket)
    invalidations = _string_list(definition.get("invalidation_conditions"))
    invalidation_price, invalidation_op = _price_invalidation(invalidations)
    status, end_at, reason = _lifecycle(bucket.rows, closure)
    return Scenario(
        id=scenario_id,
        label=seed.event.label,
        direction=str(definition.get("direction") or ""),
        setup_type=str(definition.get("setup_type") or ""),
        confidence=str(definition.get("confidence") or ""),
        source=seed.source,
        book=seed.book,
        created_time=to_chart_time(seed.event.at),
        end_time=_end_time(end_at, seed.event.at),
        status=status,
        terminal_reason=reason,
        ttl_minutes=json_int(definition.get("ttl_minutes")),
        trigger_zone=_trigger_zone(definition.get("trigger_zone")),
        target_price=json_float(definition.get("target_price")),
        invalidation_price=invalidation_price,
        invalidation_op=invalidation_op,
        trigger_conditions=_string_list(definition.get("trigger_conditions")),
        invalidation_conditions=invalidations,
        events=_events(bucket),
        evaluation_ids=[],
    )


def _end_time(end_at: datetime | None, created_at: datetime) -> int | None:
    """Chart end time, never before creation (a dedup expiry can precede its created row)."""
    if end_at is None:
        return None
    return to_chart_time(max(end_at, created_at))


def _events(bucket: _Bucket) -> list[ScenarioEvent]:
    """Return the created event first, then attached rows in time order."""
    rows = bucket.rows
    if bucket.seed.source != UNLOGGED_SOURCE:
        rows = (bucket.seed.event, *rows)
    return [_event(row) for row in rows]


def _definition_row(bucket: _Bucket) -> JsonRow:
    """Return the first row carrying the scenario definition; signal rows carry none."""
    rows = (bucket.seed.event, *bucket.rows)
    return next((t.row for t in rows if "trigger_conditions" in t.row), bucket.seed.event.row)


def _lifecycle(
    rows: tuple[_TimedRow, ...], closure: _Closure | None
) -> tuple[str, datetime | None, str | None]:
    """Return (status, end, terminal_reason); the first terminal row wins."""
    terminal = next((row for row in rows if row.status in TERMINAL_STATUSES), None)
    if terminal is not None:
        return terminal.status, terminal.at, str(terminal.row.get("reason") or "") or None
    if closure is not None:
        return "superseded", closure.at, closure.reason
    if any(row.status == "triggered" for row in rows):
        return "triggered", None, None
    return "open", None, None


def _event(timed: _TimedRow) -> ScenarioEvent:
    return ScenarioEvent(
        time=to_chart_time(timed.at),
        kind=timed.status,
        text=_event_text(timed),
        price=_event_price(timed),
    )


def _event_text(timed: _TimedRow) -> str:
    if timed.status == "entry_timing":
        return str(timed.row.get("decision") or "")
    if timed.status in TERMINAL_STATUSES:
        return str(timed.row.get("reason") or "")
    return ""


def _event_price(timed: _TimedRow) -> float | None:
    if timed.status.startswith("signal_"):
        return json_float(timed.row.get("entry_price"))
    snapshot = timed.row.get("snapshot_at_event")
    return json_float(snapshot.get("price")) if isinstance(snapshot, dict) else None


def _price_invalidation(conditions: list[str]) -> tuple[float | None, str | None]:
    """Return (price, operator) of the first `price <op> <number>` condition."""
    for condition in conditions:
        match = _PRICE_RULE.match(condition)
        if match:
            return float(match.group(2)), match.group(1)
    return None, None


def _trigger_zone(value: object) -> TriggerZone | None:
    if not isinstance(value, dict):
        return None
    low, high = json_float(value.get("low")), json_float(value.get("high"))
    if low is None or high is None:
        return None
    return TriggerZone(low=low, high=high)


def _entered_scenario_id(scenarios: list[Scenario], trade: Trade) -> str | None:
    entry_time = trade["entry"]["time"]
    scenario_id = resolve_scenario_id(scenarios, trade["scenario_label"], entry_time)
    scenario = next((s for s in scenarios if s["id"] == scenario_id), None)
    if scenario is None:
        return None
    end_time = scenario["end_time"]
    return scenario_id if end_time is None or entry_time <= end_time else None


def _with_status(scenario: Scenario, status: str) -> Scenario:
    updated = scenario.copy()
    updated["status"] = status
    return updated


def _string_list(value: object) -> list[str]:
    return [str(item) for item in value] if isinstance(value, list) else []
