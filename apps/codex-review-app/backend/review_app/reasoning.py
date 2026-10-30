"""Extract the agents' recorded answers; never regenerate their reasoning."""

from __future__ import annotations

import json
import re
from pathlib import Path

from review_app.records import Row, identity, read_text, source, timestamp
from review_app.scenarios import scenario_at

HEADER = re.compile(
    r"^### Tick #(\d+) \| ([^|\n]+) \| (\d\d:\d\d:\d\d) \| ([\d.]+)ms\s*$", re.MULTILINE
)
RESPONSE = re.compile(r"\*\*Response\*\*:\s*\n```[^\n]*\n(.*?)\n```", re.DOTALL)
HUMAN = re.compile(r"<summary>Human message[^\n]*</summary>\s*\n```[^\n]*\n(.*?)\n```", re.DOTALL)


def response_object(raw: str) -> Row:
    try:
        start = raw.index("{")
        result, _ = json.JSONDecoder().raw_decode(raw[start:])
        return result if isinstance(result, dict) else {}
    except (ValueError, TypeError):
        return {}


UNPARSED_REASONING = "Response could not be parsed; see original response."
TEXT_FIELDS = ("decision", "reasoning", "case_for", "case_against", "verdict", "wait_for")


def agent_card(
    name: str, raw: str, model: str, record_source: str, when: int, warnings: list[str]
) -> Row:
    """One agent's answer; fields of the wrong JSON type are dropped with a warning."""
    parsed = valid_fields(response_object(raw), name, record_source, warnings)
    return {
        "name": name,
        "model": model,
        "decision": parsed.get("decision", "unavailable"),
        "reasoning": parsed.get("reasoning", UNPARSED_REASONING),
        "case_for": parsed.get("case_for", parsed.get("bull_case", "")),
        "case_against": parsed.get("case_against", parsed.get("bear_case", "")),
        "verdict": parsed.get("verdict", ""),
        "wait_for": parsed.get("wait_for", ""),
        "key_factors": parsed.get("key_factors", []),
        "raw": raw,
        "source": record_source,
        "time": when,
    }


def valid_fields(parsed: Row, name: str, record_source: str, warnings: list[str]) -> Row:
    """Keep text fields that are strings and key_factors that is a list of strings."""
    valid: Row = {}
    for key, value in parsed.items():
        if key in (*TEXT_FIELDS, "bull_case", "bear_case"):
            ok = isinstance(value, str) or (key == "wait_for" and value is None)
        elif key == "key_factors":
            ok = isinstance(value, list) and all(isinstance(item, str) for item in value)
        else:
            continue
        if ok:
            valid[key] = value
        else:
            warnings.append(
                f"{record_source}: {name} response field '{key}' is "
                f"{type(value).__name__}, not text; shown in the original response only."
            )
    return valid


def read_decisions(path: Path, root: Path, day: str, warnings: list[str]) -> list[Row]:
    text = read_text(path, warnings)
    headers = list(HEADER.finditer(text))
    groups: list[Row] = []
    for index, header in enumerate(headers):
        role = header[2].strip()
        if role not in {"entry_timing:opus", "entry_timing:astra"}:
            continue
        block = text[
            header.end() : headers[index + 1].start() if index + 1 < len(headers) else len(text)
        ]
        add_trace(groups, path, root, day, text, header, block, warnings)
    return groups


def add_trace(
    groups: list[Row],
    path: Path,
    root: Path,
    day: str,
    text: str,
    header: re.Match[str],
    block: str,
    warnings: list[str],
) -> None:
    human_match, response_match = HUMAN.search(block), RESPONSE.search(block)
    human = human_match[1] if human_match else ""
    label = re.search(r"^Label:\s*(.+)$", human, re.MULTILINE)
    when = timestamp(f"{day}T{header[3]}")
    if not label or when is None:
        return
    name = header[2].strip().split(":")[1]
    record_source = source(path, root, text.count("\n", 0, header.start()) + 1)
    pair_key = identity(header[1], human)
    previous = groups[-1] if groups else None
    if (
        previous is None
        or previous["pair_key"] != pair_key
        or name in previous["agents"]
        or when - previous["time"] > 600
    ):
        previous = {
            "id": identity(day, record_source),
            "pair_key": pair_key,
            "label": label[1].strip(),
            "time": when,
            "agents": {},
            "source": record_source,
            "scenario_id": None,
            "consensus": "unavailable",
            "link_status": "unmatched",
        }
        groups.append(previous)
    model_match = re.search(r"\*\*Model\*\*:\s*`([^`]+)`", block)
    raw = response_match[1] if response_match else "Response missing or incomplete."
    model = model_match[1] if model_match else "Unknown"
    previous["agents"][name] = agent_card(name, raw, model, record_source, when, warnings)


def link_decisions(decisions: list[Row], scenarios: list[Row]) -> None:
    candidates = [
        (s, e) for s in scenarios for e in s["events"] if e.get("status") == "entry_timing"
    ]
    used: set[str] = set()
    for decision in decisions:
        matches = [
            (s, e)
            for s, e in candidates
            if s["label"] == decision["label"]
            and 0 <= decision["time"] - e["time"] <= 600
            and e["source"] not in used
        ]
        # Consensus text is stronger evidence than timestamps when calls share a tick.
        reasons = [a["reasoning"] for a in decision["agents"].values() if a.get("reasoning")]
        exact = [
            (s, e)
            for s, e in matches
            if reasons and all(r in e.get("reasoning", "") for r in reasons)
        ]
        matches = exact or matches
        if len(matches) == 1:
            scenario, event = matches[0]
            used.add(event["source"])
            decision.update(
                scenario_id=scenario["id"],
                time=event["time"],
                consensus=event.get("decision", "unavailable"),
                link_status="recorded reasoning + time" if exact else "label + time",
                event_source=event["source"],
            )
            scenario["decisions"].append(decision["id"])
        elif len(matches) > 1:
            decision["link_status"] = "ambiguous"
        else:
            scenario = scenario_at(scenarios, decision["label"], decision["time"])
            if scenario:
                decision.update(
                    scenario_id=scenario["id"],
                    link_status="label + lifetime; consensus record missing",
                )
                scenario["decisions"].append(decision["id"])
    add_untraced_decisions(decisions, scenarios, used)


def add_untraced_decisions(decisions: list[Row], scenarios: list[Row], used: set[str]) -> None:
    for scenario in scenarios:
        for event in scenario["events"]:
            if event.get("status") != "entry_timing" or event["source"] in used:
                continue
            row = {
                "id": identity(event["source"]),
                "label": scenario["label"],
                "time": event["time"],
                "scenario_id": scenario["id"],
                "agents": {},
                "consensus": event.get("decision", "unavailable"),
                "source": event["source"],
                "link_status": "Agent traces unavailable",
                "recorded_reasoning": event.get("reasoning", ""),
            }
            decisions.append(row)
            scenario["decisions"].append(row["id"])
    decisions.sort(key=lambda row: row["time"])
