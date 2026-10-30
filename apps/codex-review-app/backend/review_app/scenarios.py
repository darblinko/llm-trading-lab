"""Reconstruct scenario revisions from lifecycle events without re-running strategy."""

from __future__ import annotations

import re

from review_app.records import Row, identity, number, timed_rows

PRICE_CLAUSE = re.compile(r"^price\s*(<=|>=|<|>)\s*(-?\d+(?:\.\d+)?)$")
TEXT_FIELDS = {
    "label": "Unnamed scenario",
    "status": "unknown",
    "direction": "",
    "setup_type": "",
    "confidence": "",
    "source_kind": "",
    "decision": "",
    "reason": "",
    "reasoning": "",
}
LIST_FIELDS = ("trigger_conditions", "invalidation_conditions")


def price_invalidations(conditions: list[str]) -> list[Row]:
    levels = []
    for condition in conditions:
        match = PRICE_CLAUSE.fullmatch(str(condition).strip())
        if match:
            levels.append({"operator": match[1], "price": float(match[2]), "condition": condition})
    return levels


def normalize_event(event: Row) -> tuple[Row, list[str]]:
    """Return the event with text, list and zone fields of the expected types.

    A field of the wrong type is replaced by its empty value; its name is returned
    so the scenario can report the malformed row.
    """
    row = dict(event)
    bad: list[str] = []
    for field, default in TEXT_FIELDS.items():
        if field in row and not isinstance(row[field], str):
            row[field] = default
            bad.append(field)
    for field in LIST_FIELDS:
        if field not in row:
            continue
        value = row[field]
        items = [item for item in value if isinstance(item, str)] if isinstance(value, list) else []
        if not isinstance(value, list) or len(items) != len(value):
            bad.append(field)
        row[field] = items
    if "trigger_zone" in row:
        row["trigger_zone"], zone_ok = _zone(row["trigger_zone"])
        if not zone_ok:
            bad.append("trigger_zone")
    return row, bad


def _zone(value: object) -> tuple[Row, bool]:
    if not isinstance(value, dict):
        return {}, False
    zone = {key: number(value[key]) for key in ("low", "high") if key in value}
    clean = {key: price for key, price in zone.items() if price is not None}
    return clean, len(clean) == len(zone)


def new_scenario(event: Row, day: str, instance: str, close: int) -> Row:
    ttl = number(event.get("ttl_minutes"))
    end = min(close, event["time"] + int(ttl * 60)) if ttl is not None else close
    return {
        "id": identity(instance, day, event["source"]),
        "date": day,
        "instance": instance,
        "label": event.get("label", "Unnamed scenario"),
        "direction": event.get("direction", ""),
        "setup_type": event.get("setup_type", ""),
        "confidence": event.get("confidence", ""),
        "zone": event.get("trigger_zone", {}),
        "target": number(event.get("target_price")),
        "start": event["time"],
        "end": end,
        "origin": event.get("source_kind", event.get("source", "")),
        "source": event["source"],
        "status": "created",
        "events": [],
        "trigger_conditions": event.get("trigger_conditions", []),
        "invalidation_conditions": event.get("invalidation_conditions", []),
        "price_invalidations": price_invalidations(event.get("invalidation_conditions", [])),
        "decisions": [],
        "fill_ids": [],
        "warnings": [],
    }


def reconstruct_scenarios(events: list[Row], day: str, instance: str, close: int) -> list[Row]:
    scenarios: list[Row] = []
    latest: dict[str, Row] = {}
    for raw_event in timed_rows(events, "event_timestamp"):
        event, bad_fields = normalize_event(raw_event)
        label = event.get("label", "Unnamed scenario")
        if event.get("status") == "created":
            if label in latest:
                latest[label]["end"] = min(latest[label]["end"], event["time"])
            current = new_scenario(event, day, instance, close)
            scenarios.append(current)
            latest[label] = current
        current = latest.get(label)
        if current is None:
            current = new_scenario(event, day, instance, close)
            current["warnings"].append(
                "Creation record missing; lifetime starts at first recorded event."
            )
            scenarios.append(current)
            latest[label] = current
        if bad_fields:
            current["warnings"].append(
                f"Malformed fields ignored in {event['source']}: {', '.join(bad_fields)}."
            )
        append_event(current, event)
    return scenarios


def append_event(scenario: Row, event: Row) -> None:
    scenario["events"].append(event)
    state = event.get("status", "unknown")
    if state in {"created", "triggered", "expired", "invalidated"} or state.startswith("signal_"):
        scenario["status"] = state
    if state in {"expired", "invalidated"}:
        scenario["end"] = min(scenario["end"], event["time"])


def scenario_at(scenarios: list[Row], label: str, when: int) -> Row | None:
    matches = [s for s in scenarios if s["label"] == label and s["start"] <= when < s["end"]]
    return matches[0] if len(matches) == 1 else None


def add_outcomes(scenarios: list[Row], candles: list[Row]) -> None:
    for scenario in scenarios:
        triggers = [e for e in scenario["events"] if e.get("status") == "triggered"]
        scenario["outcome"] = measure_outcome(scenario, triggers, candles)


def measure_outcome(scenario: Row, triggers: list[Row], candles: list[Row]) -> Row:
    if not triggers:
        return {"label": "Never triggered", "detail": "No trigger event was recorded."}
    start = triggers[0]["time"]
    bars = [b for b in candles if start <= b["time"] and b["time"] + 180 <= scenario["end"]]
    if not bars:
        return {
            "label": "Outcome unavailable",
            "detail": "No complete candles within the post-trigger lifetime.",
        }
    target = scenario["target"]
    hit = next(
        (
            b
            for b in bars
            if target is not None
            and (b["high"] >= target if scenario["direction"] == "call" else b["low"] <= target)
        ),
        None,
    )
    invalid = next(
        (b for b in bars if any(_breached(b, c) for c in scenario["price_invalidations"])), None
    )
    label = "Target not touched"
    if hit:
        label = "Target touched"
        if invalid and hit["time"] == invalid["time"]:
            label = "Target / invalidation order unknown"
        elif invalid and invalid["time"] < hit["time"]:
            label = "Target touched after price invalidation"
    return {
        "label": label,
        "detail": (
            "Complete candles after the first trigger, within this revision's lifetime. "
            "Price touches are not fills."
        ),
        "target_time": hit["time"] if hit else None,
        "price_change": round(bars[-1]["close"] - bars[0]["open"], 4),
    }


def _breached(bar: Row, clause: Row) -> bool:
    value = bar["low"] if clause["operator"].startswith("<") else bar["high"]
    price = clause["price"]
    return {"<": value < price, "<=": value <= price, ">": value > price, ">=": value >= price}[
        clause["operator"]
    ]
