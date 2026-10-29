"""Tests for claude_review.scenarios."""

import copy

from claude_review.chart_time import to_chart_time
from claude_review.log_files import JsonRow
from claude_review.payload_types import Fill, Trade
from claude_review.scenarios import build_scenarios, link_trades, resolve_scenario_id

DAY = "2026-09-24"


def _at(clock: str) -> str:
    return f"{DAY}T{clock}-04:00"


def _chart(clock: str) -> int:
    return to_chart_time(_at(clock))


def _definition(label: str, **overrides: object) -> JsonRow:
    base: JsonRow = {
        "label": label,
        "direction": "put",
        "setup_type": "bear_continuation",
        "confidence": "medium",
        "ttl_minutes": None,
        "trigger_zone": {"low": 734.7, "high": 736.2},
        "target_price": 732.6,
        "trigger_conditions": ["price < level_a", "momentum < 0"],
        "invalidation_conditions": ["range_ratio > 1.5", "price > 738.80"],
    }
    return {**base, **overrides}


def _created(clock: str, label: str, source: str = "initial_thesis", **fields: object) -> JsonRow:
    return {
        "event_timestamp": _at(clock),
        "status": "created",
        "source": source,
        **_definition(label, **fields),
    }


def _row(clock: str, status: str, label: str, **fields: object) -> JsonRow:
    return {"event_timestamp": _at(clock), "status": status, **_definition(label), **fields}


def _signal(clock: str, result: str, label: str, entry_price: str) -> JsonRow:
    return {
        "event_timestamp": _at(clock),
        "status": f"signal_{result}",
        "label": label,
        "direction": "put",
        "entry_price": entry_price,
    }


def _only(rows: list[JsonRow]) -> dict:
    scenarios = build_scenarios(rows)
    assert len(scenarios) == 1
    return dict(scenarios[0])


def test_created_row_becomes_open_scenario_with_definition() -> None:
    scenario = _only([_created("10:25:53.190185", "Level break put")])

    assert scenario["id"] == "Level break put@10:25:53"
    assert scenario["label"] == "Level break put"
    assert scenario["source"] == "initial_thesis"
    assert scenario["book"] == "Initial 10:25"
    assert scenario["created_time"] == _chart("10:25:53")
    assert scenario["end_time"] is None
    assert scenario["status"] == "open"
    assert scenario["terminal_reason"] is None
    assert scenario["direction"] == "put"
    assert scenario["setup_type"] == "bear_continuation"
    assert scenario["confidence"] == "medium"
    assert scenario["trigger_zone"] == {"low": 734.7, "high": 736.2}
    assert scenario["target_price"] == 732.6
    assert scenario["trigger_conditions"] == ["price < level_a", "momentum < 0"]
    assert scenario["invalidation_price"] == 738.8
    assert scenario["invalidation_op"] == ">"
    assert scenario["evaluation_ids"] == []
    assert scenario["events"] == [
        {"time": _chart("10:25:53"), "kind": "created", "text": "", "price": None}
    ]


def test_invalidation_without_price_rule_gives_none() -> None:
    scenario = _only(
        [_created("10:25:53", "A", invalidation_conditions=["price < level_a", "rsi > 70"])]
    )

    assert scenario["invalidation_price"] is None
    assert scenario["invalidation_op"] is None


def test_refresh_rows_form_a_refresh_book() -> None:
    scenarios = build_scenarios(
        [
            _created("09:32:07.1", "A"),
            _created("11:36:18.2", "B", source="thesis_refresh"),
        ]
    )

    assert [s["book"] for s in scenarios] == ["Initial 09:32", "Refresh 11:36"]


def test_book_batch_straddling_a_minute_keeps_one_name() -> None:
    scenarios = build_scenarios(
        [_created("10:25:59.999900", "A"), _created("10:26:00.000100", "B")]
    )

    assert [s["book"] for s in scenarios] == ["Initial 10:25", "Initial 10:25"]


def test_lifecycle_events_carry_price_and_text() -> None:
    snapshot = {"price": 735.2, "rsi": 40.0}
    scenario = _only(
        [
            _created("10:25:53", "A"),
            _row("11:10:50", "triggered", "A", snapshot_at_event=snapshot),
            _row(
                "11:10:50.5",
                "entry_timing",
                "A",
                decision="enter_now",
                reasoning="r",
                snapshot_at_event=snapshot,
            ),
            _signal("11:11:51", "confirmed", "A", "735.2"),
        ]
    )

    assert scenario["status"] == "triggered"
    assert scenario["end_time"] is None
    assert [(e["kind"], e["text"], e["price"]) for e in scenario["events"]] == [
        ("created", "", None),
        ("triggered", "", 735.2),
        ("entry_timing", "enter_now", 735.2),
        ("signal_confirmed", "", 735.2),
    ]


def test_invalidated_row_closes_the_scenario() -> None:
    scenario = _only(
        [
            _created("10:25:53", "A"),
            _row("12:16:57", "invalidated", "A", reason="Invalidation: price > 737.60"),
        ]
    )

    assert scenario["status"] == "invalidated"
    assert scenario["end_time"] == _chart("12:16:57")
    assert scenario["terminal_reason"] == "Invalidation: price > 737.60"
    assert scenario["events"][-1]["text"] == "Invalidation: price > 737.60"


def test_expired_after_trigger_reports_expired() -> None:
    scenario = _only(
        [
            _created("10:25:53", "A"),
            _row("11:00:00", "triggered", "A", snapshot_at_event={"price": 735.0}),
            _row("12:04:37", "expired", "A", reason="Dropped by thesis refresh"),
        ]
    )

    assert scenario["status"] == "expired"
    assert scenario["terminal_reason"] == "Dropped by thesis refresh"


def test_input_order_does_not_matter() -> None:
    rows = [
        _row("12:16:57", "invalidated", "A", reason="x"),
        _created("10:25:53", "A"),
    ]

    assert _only(rows)["status"] == "invalidated"


def test_new_revision_supersedes_an_open_older_one() -> None:
    scenarios = build_scenarios(
        [
            _created("09:32:07", "A"),
            _created("12:04:37", "A", source="thesis_refresh", target_price=730.0),
            _row("12:30:00", "triggered", "A", snapshot_at_event={"price": 735.0}),
        ]
    )

    older, newer = scenarios
    assert older["status"] == "superseded"
    assert older["end_time"] == _chart("12:04:37")
    assert older["terminal_reason"] is not None
    assert [e["kind"] for e in older["events"]] == ["created"]
    assert newer["status"] == "triggered"
    assert newer["target_price"] == 730.0
    assert newer["id"] == "A@12:04:37"


def test_revision_does_not_override_a_terminal_row() -> None:
    older, _ = build_scenarios(
        [
            _created("09:32:07", "A"),
            _row("10:00:00", "invalidated", "A", reason="Invalidation: price > 738.80"),
            _created("12:04:37", "A", source="thesis_refresh"),
        ]
    )

    assert older["status"] == "invalidated"
    assert older["end_time"] == _chart("10:00:00")


def test_drop_row_just_before_same_label_recreation_stays_with_older() -> None:
    older, newer = build_scenarios(
        [
            _created("09:32:07", "A"),
            _row("12:04:37.100", "expired", "A", reason="Dropped by thesis refresh"),
            _created("12:04:37.200", "A", source="thesis_refresh"),
        ]
    )

    assert older["status"] == "expired"
    assert newer["status"] == "open"


def test_new_initial_book_supersedes_open_scenarios_of_earlier_books() -> None:
    scenarios = build_scenarios(
        [
            _created("10:25:53", "A"),
            _created("10:25:53.1", "B"),
            _row("10:30:00", "invalidated", "B", reason="Invalidation: price > 738.80"),
            _created("11:00:00", "C", source="thesis_refresh"),
            _created("11:44:57", "D"),
        ]
    )

    by_label = {s["label"]: s for s in scenarios}
    assert by_label["A"]["status"] == "superseded"
    assert by_label["A"]["end_time"] == _chart("11:44:57")
    assert by_label["B"]["status"] == "invalidated"
    assert by_label["C"]["status"] == "superseded"
    assert by_label["D"]["status"] == "open"
    assert by_label["D"]["book"] == "Initial 11:44"


def test_same_label_same_second_gets_unique_ids() -> None:
    scenarios = build_scenarios([_created("10:25:53.1", "A"), _created("10:25:53.2", "A")])

    assert [s["id"] for s in scenarios] == ["A@10:25:53", "A@10:25:53#2"]


def test_dedup_expiry_logged_before_its_created_row_attaches_to_it() -> None:
    scenario = _only(
        [
            _row("14:02:09.100", "expired", "A", reason="Zone-dedup on refresh"),
            _created("14:02:09.300", "A", source="thesis_refresh"),
        ]
    )

    assert scenario["source"] == "thesis_refresh"
    assert scenario["status"] == "expired"
    assert scenario["terminal_reason"] == "Zone-dedup on refresh"
    assert [e["kind"] for e in scenario["events"]] == ["created", "expired"]


def test_dedup_expiry_across_a_second_boundary_never_ends_before_creation() -> None:
    scenario = _only(
        [
            _row("14:02:09.900", "expired", "A", reason="Zone-dedup on refresh"),
            _created("14:02:10.100", "A", source="thesis_refresh"),
        ]
    )

    assert scenario["end_time"] == scenario["created_time"] == _chart("14:02:10")


def test_orphan_activity_row_creates_unlogged_scenario() -> None:
    scenario = _only(
        [
            _row("11:55:57", "triggered", "A", snapshot_at_event={"price": 739.0}),
            _row("11:55:57.5", "entry_timing", "A", decision="pass"),
            _row("12:40:57", "invalidated", "A", reason="Invalidation: price > 740.60"),
        ]
    )

    assert scenario["source"] == "unlogged"
    assert scenario["book"] == "Unlogged"
    assert scenario["created_time"] == _chart("11:55:57")
    assert scenario["status"] == "invalidated"
    assert scenario["trigger_zone"] == {"low": 734.7, "high": 736.2}
    assert [e["kind"] for e in scenario["events"]] == ["triggered", "entry_timing", "invalidated"]


def test_orphan_signal_row_creates_minimal_unlogged_scenario() -> None:
    scenario = _only([_signal("11:11:51", "confirmed", "A", "735.2")])

    assert scenario["source"] == "unlogged"
    assert scenario["trigger_zone"] is None
    assert scenario["trigger_conditions"] == []
    assert scenario["target_price"] is None


def test_orphan_terminal_only_rows_are_dropped() -> None:
    rows = [
        _row("00:00:54", "expired", "VWAP reclaim B", reason="Zone-dedup on refresh"),
        _row("17:30:05", "expired", "VWAP reclaim B", reason="Zone-dedup on refresh"),
        _created("09:32:07", "A"),
    ]

    assert [s["label"] for s in build_scenarios(rows)] == ["A"]


def test_rows_without_timestamp_or_label_are_skipped() -> None:
    rows = [
        _created("09:32:07", "A"),
        {"status": "triggered", "label": "A"},
        {"event_timestamp": _at("10:00:00"), "status": "triggered"},
    ]

    assert [e["kind"] for e in _only(rows)["events"]] == ["created"]


def test_resolve_scenario_id_picks_latest_created_at_or_before() -> None:
    scenarios = build_scenarios(
        [_created("09:32:07", "A"), _created("12:04:37", "A", source="thesis_refresh")]
    )

    assert resolve_scenario_id(scenarios, "A", _chart("09:00:00")) is None
    assert resolve_scenario_id(scenarios, "A", _chart("09:32:07")) == "A@09:32:07"
    assert resolve_scenario_id(scenarios, "A", _chart("12:04:36")) == "A@09:32:07"
    assert resolve_scenario_id(scenarios, "A", _chart("13:00:00")) == "A@12:04:37"
    assert resolve_scenario_id(scenarios, "B", _chart("13:00:00")) is None


def _trade(label: str, entry_clock: str) -> Trade:
    entry = Fill(
        time=_chart(entry_clock), underlying_price=735.4, option_price=0.9, qty=10, reason=""
    )
    return Trade(
        id=f"QQQ@{entry_clock}",
        contract="QQQ260924P00734000",
        direction="put",
        scenario_label=label,
        qty=10,
        entry=entry,
        exits=[],
        realized_pnl=None,
        open=True,
    )


def test_link_trades_marks_entered_and_keeps_reason() -> None:
    scenarios = build_scenarios(
        [
            _created("10:25:53", "A"),
            _created("10:25:53.1", "B"),
            _created("11:44:57", "C"),
        ]
    )
    before = copy.deepcopy(scenarios)

    linked = link_trades(scenarios, [_trade("A", "11:12:51")])

    by_label = {s["label"]: s for s in linked}
    assert by_label["A"]["status"] == "entered"
    assert by_label["A"]["terminal_reason"] == scenarios[0]["terminal_reason"]
    assert by_label["A"]["end_time"] == _chart("11:44:57")
    assert by_label["B"]["status"] == "superseded"
    assert by_label["C"]["status"] == "open"
    assert scenarios == before


def test_link_trades_ignores_entries_outside_the_lifetime() -> None:
    scenarios = build_scenarios(
        [
            _created("10:25:53", "A"),
            _row("10:40:00", "invalidated", "A", reason="Invalidation: price > 738.80"),
        ]
    )

    early = link_trades(scenarios, [_trade("A", "10:00:00")])
    late = link_trades(scenarios, [_trade("A", "10:45:00")])

    assert early[0]["status"] == "invalidated"
    assert late[0]["status"] == "invalidated"


def test_link_trades_picks_the_revision_live_at_entry() -> None:
    scenarios = build_scenarios(
        [_created("09:32:07", "A"), _created("12:04:37", "A", source="thesis_refresh")]
    )

    linked = link_trades(scenarios, [_trade("A", "12:30:00")])

    assert [s["status"] for s in linked] == ["superseded", "entered"]
