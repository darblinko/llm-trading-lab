"""Tests for claude_review.trades."""

import pytest
from claude_review.chart_time import to_chart_time
from claude_review.log_files import JsonRow
from claude_review.trades import build_trades

DAY = "2026-09-17"
CALL = "QQQ260917C00717000"
PUT = "QQQ260917P00716000"


def _at(clock: str) -> str:
    return f"{DAY}T{clock}-04:00"


def _chart(clock: str) -> int:
    return to_chart_time(_at(clock))


def _buy_metadata(
    label: str = "EMA-21 hold", direction: str = "call", spot: float = 716.575
) -> JsonRow:
    return {"direction": direction, "scenario_label": label, "spot_price": spot, "chunk": 1}


def _order(
    clock: str,
    order_id: str,
    side: str,
    qty: int,
    price: float,
    symbol: str = CALL,
    action: str = "fill",
    reason: str = "",
    metadata: JsonRow | None = None,
) -> JsonRow:
    return {
        "timestamp": _at(clock),
        "action": action,
        "client_order_id": order_id,
        "symbol": symbol,
        "side": side,
        "status": "filled" if action == "fill" else action,
        "qty_requested": qty,
        "qty_filled": qty,
        "avg_fill_price": price,
        "reason": reason,
        "metadata": metadata if metadata is not None else {},
    }


def _buy(
    clock: str, order_id: str, qty: int, price: float, symbol: str = CALL, **meta: object
) -> JsonRow:
    return _order(clock, order_id, "buy", qty, price, symbol=symbol, metadata=_buy_metadata(**meta))


def _sell(
    clock: str, order_id: str, qty: int, price: float, reason: str, symbol: str = CALL
) -> JsonRow:
    return _order(clock, order_id, "sell", qty, price, symbol=symbol, reason=reason)


def _tick(clock: str, price: float) -> JsonRow:
    return {"timestamp": _at(clock), "price": price}


def test_one_round_trip_merges_entry_and_exit_chunks() -> None:
    orders = [
        _order("13:45:08", "b1", "buy", 100, 0.49, action="intent", metadata=_buy_metadata()),
        _buy("13:45:09.1", "b1", 100, 0.49),
        _buy("13:45:09.2", "b2", 20, 0.50),
        _sell("14:37:14.1", "s1", 100, 0.24, "Hard stop: -50%"),
        _sell("14:37:14.9", "s2", 20, 0.24, "Hard stop: -50%"),
    ]
    ticks = [_tick("14:36:00", 715.1), _tick("14:37:00", 715.2), _tick("14:38:00", 715.3)]

    (trade,) = build_trades(orders, ticks)

    assert trade["id"] == f"{CALL}@13:45:09"
    assert trade["contract"] == CALL
    assert trade["direction"] == "call"
    assert trade["scenario_label"] == "EMA-21 hold"
    assert trade["qty"] == 120
    assert trade["open"] is False
    assert trade["entry"]["time"] == _chart("13:45:09")
    assert trade["entry"]["qty"] == 120
    assert trade["entry"]["option_price"] == pytest.approx((100 * 0.49 + 20 * 0.50) / 120, abs=1e-4)
    assert trade["entry"]["underlying_price"] == 716.575
    assert trade["entry"]["reason"] == ""
    assert trade["exits"] == [
        {
            "time": _chart("14:37:14"),
            "underlying_price": 715.2,
            "option_price": 0.24,
            "qty": 120,
            "reason": "Hard stop: -50%",
        }
    ]
    expected_pnl = (0.24 * 120 - (100 * 0.49 + 20 * 0.50)) * 100
    assert trade["realized_pnl"] == pytest.approx(expected_pnl, abs=0.01)


def test_two_trades_in_one_contract_stay_separate() -> None:
    orders = [
        _buy("10:00:00", "b1", 10, 1.00, label="first"),
        _sell("10:10:00", "s1", 10, 1.50, "TP"),
        _buy("11:00:00", "b2", 5, 2.00, label="second"),
        _sell("11:20:00", "s2", 5, 1.00, "Hard stop"),
    ]

    trades = build_trades(orders, [])

    assert [t["scenario_label"] for t in trades] == ["first", "second"]
    assert [t["realized_pnl"] for t in trades] == [pytest.approx(500.0), pytest.approx(-500.0)]
    assert [t["id"] for t in trades] == [f"{CALL}@10:00:00", f"{CALL}@11:00:00"]


def test_interleaved_contracts_are_grouped_per_contract() -> None:
    orders = [
        _buy("13:45:09", "c1", 10, 0.49),
        _buy("13:56:23", "p1", 20, 0.49, symbol=PUT, label="put scenario", direction="put"),
        _sell("14:12:41", "p2", 20, 0.45, "Max hold", symbol=PUT),
        _sell("14:37:14", "c2", 10, 0.24, "Hard stop"),
    ]

    trades = build_trades(orders, [])

    assert [(t["contract"], t["qty"], t["open"]) for t in trades] == [
        (CALL, 10, False),
        (PUT, 20, False),
    ]
    assert trades[1]["direction"] == "put"


def test_partial_fills_are_cumulative_and_counted_once() -> None:
    orders = [
        _order("10:00:00", "b1", "buy", 40, 1.00, action="partial_fill", metadata=_buy_metadata()),
        _order("10:00:30", "b1", "buy", 100, 1.02, action="fill", metadata=_buy_metadata()),
        _sell("10:30:00", "s1", 100, 1.10, "TP"),
    ]

    (trade,) = build_trades(orders, [])

    assert trade["qty"] == 100
    assert trade["entry"]["time"] == _chart("10:00:00")
    assert trade["entry"]["option_price"] == pytest.approx(1.02)
    assert trade["open"] is False


def test_partial_fill_of_a_cancelled_order_counts_its_filled_qty() -> None:
    orders = [
        _order("10:00:00", "b1", "buy", 40, 1.00, action="partial_fill", metadata=_buy_metadata()),
        _sell("10:30:00", "s1", 40, 1.10, "TP"),
    ]

    (trade,) = build_trades(orders, [])

    assert trade["qty"] == 40
    assert trade["open"] is False


def test_open_position_without_exits() -> None:
    (trade,) = build_trades([_buy("11:12:51", "b1", 10, 0.90)], [])

    assert trade["open"] is True
    assert trade["exits"] == []
    assert trade["realized_pnl"] is None


def test_partially_exited_position_stays_open_with_realized_part() -> None:
    orders = [_buy("10:00:00", "b1", 10, 1.00), _sell("10:05:00", "s1", 4, 1.50, "TP tier 1/3")]

    (trade,) = build_trades(orders, [])

    assert trade["open"] is True
    assert trade["realized_pnl"] == pytest.approx(200.0)


def test_adding_after_a_partial_exit_leaves_earlier_realized_profit_unchanged() -> None:
    orders = [
        _buy("10:00:00", "b1", 2, 1.00),
        _sell("10:05:00", "s1", 1, 2.00, "TP tier 1/3"),
        _buy("10:10:00", "b2", 1, 3.00),
    ]

    (trade,) = build_trades(orders, [])

    assert trade["open"] is True
    assert trade["realized_pnl"] == pytest.approx(100.0)


def test_sale_after_an_add_uses_the_average_cost_at_that_time() -> None:
    orders = [
        _buy("10:00:00", "b1", 2, 1.00),
        _sell("10:05:00", "s1", 1, 2.00, "TP tier 1/3"),
        _buy("10:10:00", "b2", 1, 3.00),
        _sell("10:20:00", "s2", 2, 2.50, "Close"),
    ]

    (trade,) = build_trades(orders, [])

    # Cost after the add is (1 x 1.00 + 1 x 3.00) / 2 = 2.00 per contract.
    assert trade["open"] is False
    assert trade["realized_pnl"] == pytest.approx(100.0 + 2 * 0.50 * 100)


def test_each_exit_decision_is_its_own_fill() -> None:
    orders = [
        _buy("14:23:25", "b1", 300, 0.47),
        _sell("14:47:07", "s1", 100, 0.74, "TP tier 1/3"),
        _sell("14:47:07.5", "s2", 50, 0.74, "TP tier 1/3"),
        _sell("14:48:09", "s3", 100, 1.03, "TP tier 2/3"),
        _sell("14:48:09.4", "s4", 50, 1.03, "TP tier 2/3"),
    ]

    (trade,) = build_trades(orders, [])

    assert [(f["reason"], f["qty"]) for f in trade["exits"]] == [
        ("TP tier 1/3", 150),
        ("TP tier 2/3", 150),
    ]
    assert trade["open"] is False


def test_same_reason_sells_far_apart_are_separate_exits() -> None:
    orders = [
        _buy("10:00:00", "b1", 20, 1.00),
        _sell("10:05:00", "s1", 10, 1.20, "Max hold"),
        _sell("10:06:00", "s2", 10, 1.30, "Max hold"),
    ]

    (trade,) = build_trades(orders, [])

    assert [f["qty"] for f in trade["exits"]] == [10, 10]


def test_exit_reason_falls_back_to_metadata_reason() -> None:
    sell = _order("12:13:57", "s1", "sell", 10, 0.79, metadata={"reason": "Max hold exceeded"})
    orders = [_buy("11:12:51", "b1", 10, 0.90), sell]

    (trade,) = build_trades(orders, [])

    assert trade["exits"][0]["reason"] == "Max hold exceeded"


def test_exit_underlying_needs_a_tick_at_or_before_the_fill() -> None:
    orders = [_buy("09:31:00", "b1", 10, 1.00), _sell("09:32:00", "s1", 10, 1.10, "TP")]

    (trade,) = build_trades(orders, [_tick("09:32:30", 700.0)])

    assert trade["exits"][0]["underlying_price"] is None


def test_exit_underlying_uses_exact_tick_time() -> None:
    orders = [_buy("09:31:00", "b1", 10, 1.00), _sell("09:32:00", "s1", 10, 1.10, "TP")]
    ticks = [_tick("09:32:00", 701.0), _tick("09:31:00", 700.0)]

    (trade,) = build_trades(orders, ticks)

    assert trade["exits"][0]["underlying_price"] == 701.0


def test_sell_without_open_position_is_skipped() -> None:
    orders = [_sell("09:40:00", "s0", 10, 1.00, "stray"), _buy("10:00:00", "b1", 10, 1.00)]

    (trade,) = build_trades(orders, [])

    assert trade["exits"] == []
    assert trade["open"] is True


def test_non_fill_actions_and_unusable_fills_are_ignored() -> None:
    orders = [
        _order("10:00:00", "b1", "buy", 10, 1.00, action="submitted", metadata=_buy_metadata()),
        _order("10:00:01", "b2", "buy", 0, 1.00, metadata=_buy_metadata()),
        {"timestamp": _at("10:00:02"), "action": "fill", "client_order_id": "b3"},
    ]

    assert build_trades(orders, []) == []


def test_trades_are_sorted_by_entry_time() -> None:
    orders = [
        _buy("13:56:23", "p1", 20, 0.49, symbol=PUT),
        _buy("13:45:09", "c1", 10, 0.49),
    ]

    trades = build_trades(orders, [])

    assert [t["contract"] for t in trades] == [CALL, PUT]
