"""Assembles the per-day JSON document served by /api/day/<YYYY-MM-DD>."""

import logging
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import NamedTuple

import pandas as pd

from claude_review.bars import BarsUnavailable, MinuteFetch, bars_to_payload, load_session_bars
from claude_review.evaluations import build_evaluations
from claude_review.indicator_series import build_indicators
from claude_review.key_levels import build_key_levels
from claude_review.log_files import JsonRow, read_jsonl, session_paths
from claude_review.payload_types import Bar, DayPayload, Evaluation, Indicators, KeyLevel, Scenario
from claude_review.scenarios import build_scenarios, link_trades, resolve_scenario_id
from claude_review.trace_parser import parse_trace
from claude_review.trades import build_trades

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DaySources:
    log_dir: Path
    cache_dir: Path
    fetch: MinuteFetch
    today: date


class MarketSection(NamedTuple):
    bars: list[Bar]
    indicators: Indicators
    key_levels: list[KeyLevel]
    warnings: list[str]


def build_day_payload(session_date: date, sources: DaySources, refresh: bool = False) -> DayPayload:
    day_text = session_date.isoformat()
    paths = session_paths(sources.log_dir, day_text)
    tick_rows = read_jsonl(paths.ticks, day_text, "timestamp")
    scenario_rows = read_jsonl(paths.scenarios, day_text, "event_timestamp")
    order_rows = read_jsonl(paths.orders, day_text, "timestamp")

    trades = build_trades(order_rows, tick_rows)
    scenarios = link_trades(build_scenarios(scenario_rows), trades)
    evaluations = _evaluations_for(scenario_rows, paths.trace, day_text, scenarios)
    market = _market_section(session_date, sources, refresh, tick_rows)
    return {
        "date": day_text,
        "is_today": session_date == sources.today,
        "warnings": market.warnings + _log_warnings(scenarios, evaluations),
        "bars": market.bars,
        "indicators": market.indicators,
        "key_levels": market.key_levels,
        "scenarios": _attach_evaluation_ids(scenarios, evaluations),
        "evaluations": evaluations,
        "trades": trades,
    }


def _evaluations_for(
    scenario_rows: list[JsonRow], trace_path: Path, day_text: str, scenarios: list[Scenario]
) -> list[Evaluation]:
    entry_timing_rows = [row for row in scenario_rows if row.get("status") == "entry_timing"]
    return build_evaluations(
        entry_timing_rows,
        parse_trace(trace_path),
        day_text,
        lambda label, when: resolve_scenario_id(scenarios, label, when),
    )


def _market_section(
    session_date: date, sources: DaySources, refresh: bool, tick_rows: list[JsonRow]
) -> MarketSection:
    try:
        session_bars = load_session_bars(
            session_date, sources.cache_dir, sources.fetch, sources.today, refresh
        )
    except BarsUnavailable as error:
        logger.warning("No bars for %s: %s", session_date, error)
        levels = build_key_levels(tick_rows, pd.DataFrame())
        return MarketSection(
            [], {"overlays": {}, "oscillators": {}}, levels, [f"Candles unavailable: {error}"]
        )
    return MarketSection(
        bars_to_payload(session_bars.bars_3m, session_date),
        build_indicators(session_bars.bars_3m, session_date),
        build_key_levels(tick_rows, session_bars.day_minute),
        [],
    )


def _attach_evaluation_ids(
    scenarios: list[Scenario], evaluations: list[Evaluation]
) -> list[Scenario]:
    ids_by_scenario: dict[str, list[str]] = {}
    for evaluation in evaluations:
        if evaluation["scenario_id"] is not None:
            ids_by_scenario.setdefault(evaluation["scenario_id"], []).append(evaluation["id"])
    return [
        {**scenario, "evaluation_ids": ids_by_scenario.get(scenario["id"], [])}
        for scenario in scenarios
    ]


def _log_warnings(scenarios: list[Scenario], evaluations: list[Evaluation]) -> list[str]:
    warnings = []
    unlogged = sum(1 for scenario in scenarios if scenario["source"] == "unlogged")
    if unlogged:
        warnings.append(
            f"{unlogged} scenario(s) have events but no created row (mid-session restart)."
        )
    unlinked = sum(1 for evaluation in evaluations if evaluation["scenario_id"] is None)
    if unlinked:
        warnings.append(f"{unlinked} evaluation(s) could not be matched to a scenario.")
    ambiguous = sum(1 for evaluation in evaluations if evaluation["link_quality"] == "ambiguous")
    if ambiguous:
        warnings.append(
            f"{ambiguous} evaluation(s) matched more than one trace entry; the earliest was used."
        )
    return warnings
