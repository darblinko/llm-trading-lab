"""Target-hit rates by family, variant and context bucket, with hierarchical shrinkage.

The family rate is the raw share of events that exit at the target. A variant
rate is shrunk toward its family rate, and a bucket rate (family, variant,
context) toward its variant's shrunk rate:

    shrunk = (hits + k * parent_rate) / (n + k)

where k is prior_strength. Aggregate rows carry None in the finer fields.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import asdict, dataclass

from swing_backtest.trades import ExitReason, TradeResult


@dataclass(frozen=True)
class ConfidenceRow:
    family: str
    variant: str | None
    context: str | None
    n: int
    hits: int
    raw_rate: float
    shrunk_rate: float


def context_key(context: Sequence[tuple[str, str]]) -> str:
    """Bucket key from (name, value) labels: "name=value;name=value", names sorted."""
    return ";".join(f"{name}={value}" for name, value in sorted(context))


def shrink(hits: int, n: int, parent_rate: float, prior_strength: float) -> float:
    return (hits + prior_strength * parent_rate) / (n + prior_strength)


def confidence_table(
    results: Iterable[TradeResult],
    prior_strength: float = 20.0,
) -> tuple[ConfidenceRow, ...]:
    """Rows ordered family, then each variant followed by its buckets."""
    if prior_strength < 0:
        raise ValueError(f"prior_strength must be >= 0, got {prior_strength}")
    rows: list[ConfidenceRow] = []
    for family, events in _grouped(results, lambda event: event.family):
        rows.extend(_family_rows(family, events, prior_strength))
    return tuple(rows)


def confidence_to_json(rows: Iterable[ConfidenceRow]) -> list[dict]:
    return [asdict(row) for row in rows]


def _family_rows(
    family: str,
    events: Sequence[TradeResult],
    prior_strength: float,
) -> list[ConfidenceRow]:
    hits = _hits(events)
    family_rate = hits / len(events)
    rows = [ConfidenceRow(family, None, None, len(events), hits, family_rate, family_rate)]
    for variant, variant_events in _grouped(events, lambda event: event.variant):
        variant_row = _row(family, variant, None, variant_events, family_rate, prior_strength)
        rows.append(variant_row)
        for context, bucket in _grouped(variant_events, lambda event: context_key(event.context)):
            rows.append(
                _row(family, variant, context, bucket, variant_row.shrunk_rate, prior_strength)
            )
    return rows


def _row(
    family: str,
    variant: str,
    context: str | None,
    events: Sequence[TradeResult],
    parent_rate: float,
    prior_strength: float,
) -> ConfidenceRow:
    hits = _hits(events)
    n = len(events)
    return ConfidenceRow(
        family,
        variant,
        context,
        n,
        hits,
        hits / n,
        shrink(hits, n, parent_rate, prior_strength),
    )


def _hits(events: Sequence[TradeResult]) -> int:
    return sum(1 for event in events if event.exit_reason == ExitReason.TARGET)


def _grouped(
    events: Iterable[TradeResult],
    key: Callable[[TradeResult], str],
) -> list[tuple[str, list[TradeResult]]]:
    groups: dict[str, list[TradeResult]] = defaultdict(list)
    for event in events:
        groups[key(event)].append(event)
    return sorted(groups.items())
