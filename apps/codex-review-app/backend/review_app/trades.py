"""Confirmed fills, cumulative-fill deduplication and position cost accounting."""

from __future__ import annotations

from review_app.records import Row, identity, number, timed_rows
from review_app.scenarios import scenario_at


def read_fills(
    records: list[Row], scenarios: list[Row], decisions: list[Row]
) -> tuple[list[Row], list[Row]]:
    orders: dict[str, Row] = {}
    positions: dict[str, Row] = {}
    fills: list[Row] = []
    for event in timed_rows(records):
        order_id = event.get("client_order_id") or event.get("broker_order_id")
        if not order_id:
            continue
        state = orders.setdefault(
            order_id, {"qty": 0, "notional": 0, "metadata": {}, "start": event["time"]}
        )
        state["metadata"].update(event.get("metadata") or {})
        fill = incremental_fill(event, state, order_id)
        if fill is None:
            continue
        attach_entry(fill, scenarios, decisions, state)
        account_fill(fill, positions)
        fills.append(fill)
        if fill["scenario_id"]:
            scenario = next(s for s in scenarios if s["id"] == fill["scenario_id"])
            scenario["fill_ids"].append(fill["id"])
    return fills, [position for position in positions.values() if position["qty"] > 0]


def incremental_fill(event: Row, state: Row, order_id: str) -> Row | None:
    confirmed = event.get("action") == "fill" or event.get("status") in {
        "filled",
        "partially_filled",
    }
    cumulative, average = number(event.get("qty_filled")), number(event.get("avg_fill_price"))
    if not confirmed or cumulative is None or average is None or cumulative <= state["qty"]:
        return None
    qty = cumulative - state["qty"]
    notional = cumulative * average
    price = (notional - state["notional"]) / qty
    if price < 0 or event.get("side") not in {"buy", "sell"}:
        return None
    state.update(qty=cumulative, notional=notional)
    broker_time = event.get("filled_at") or event.get("executed_at")
    from review_app.records import timestamp

    executed = timestamp(broker_time)
    return {
        "id": identity(order_id, cumulative),
        "order_id": order_id,
        "symbol": event.get("symbol", ""),
        "side": event["side"],
        "qty": qty,
        "price": round(price, 6),
        "time": executed or event["time"],
        "time_basis": "Broker execution time" if executed else "Recorded fill-detection time",
        "reason": event.get("reason") or state["metadata"].get("reason", ""),
        "source": event["source"],
        "scenario_id": None,
        "decision_id": None,
        "pnl": None,
        "warnings": [],
        "direction": state["metadata"].get("direction", ""),
    }


def attach_entry(fill: Row, scenarios: list[Row], decisions: list[Row], state: Row) -> None:
    if fill["side"] != "buy":
        return
    label = state["metadata"].get("scenario_label", "")
    scenario = scenario_at(scenarios, label, state["start"])
    if not scenario:
        fill["warnings"].append("No unique scenario revision matches this entry.")
        return
    fill["scenario_id"] = scenario["id"]
    matches = [
        d for d in decisions if d["scenario_id"] == scenario["id"] and d["time"] <= fill["time"]
    ]
    if matches:
        fill["decision_id"] = max(matches, key=lambda row: row["time"])["id"]


def account_fill(fill: Row, positions: dict[str, Row]) -> None:
    symbol = fill["symbol"]
    position = positions.setdefault(
        symbol, {"symbol": symbol, "qty": 0, "cost": 0, "scenario_ids": [], "decision_id": None}
    )
    if fill["side"] == "buy":
        if position["qty"] == 0:
            position.update(cost=0, scenario_ids=[], decision_id=fill["decision_id"])
        position["qty"] += fill["qty"]
        position["cost"] += fill["qty"] * fill["price"]
        if fill["scenario_id"] not in position["scenario_ids"]:
            position["scenario_ids"].append(fill["scenario_id"])
    else:
        account_exit(fill, position)
    position["average_price"] = position["cost"] / position["qty"] if position["qty"] else None


def account_exit(fill: Row, position: Row) -> None:
    if position["qty"] < fill["qty"]:
        fill["warnings"].append(
            "Entry inventory is incomplete; realized profit or loss cannot be established."
        )
        position.update(qty=0, cost=0, scenario_ids=[])
        return
    cost = position["cost"] / position["qty"]
    fill["pnl"] = round((fill["price"] - cost) * fill["qty"] * 100, 2)
    if len(position["scenario_ids"]) == 1 and position["scenario_ids"][0]:
        fill["scenario_id"] = position["scenario_ids"][0]
        fill["decision_id"] = position["decision_id"]
    else:
        fill["warnings"].append("Position contains entries without a unique scenario attribution.")
    position["qty"] -= fill["qty"]
    position["cost"] = cost * position["qty"]
