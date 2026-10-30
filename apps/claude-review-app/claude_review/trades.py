"""Round-trip trades rebuilt from the orders JSONL log.

Fills are grouped per contract into flat-to-flat position cycles, so two
trades in the same contract stay separate. One entry or exit decision is
submitted as up to 10 chunk orders; the chunks of an entry are merged into
one entry Fill, and consecutive sells with the same reason within
EXIT_GROUP_WINDOW are merged into one exit Fill.

The log reports cumulative quantity and average price per order. Each increase
becomes its own execution at the time it was reported, so a late fill on an
earlier order is accounted for when it arrived. A cycle whose sales exceed the
recorded buys has unknown cost basis: it is flagged inventory_incomplete and
its realized_pnl is None.

Fill times are the trader's poll-detection times, not broker execution times.
"""

import logging
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta
from typing import NamedTuple

from claude_review.chart_time import to_chart_time
from claude_review.log_files import JsonRow, json_float, json_int, parse_timestamp
from claude_review.payload_types import Fill, Trade

logger = logging.getLogger(__name__)

FILL_ACTIONS = frozenset({"fill", "partial_fill"})
SIDES = frozenset({"buy", "sell"})
CONTRACT_MULTIPLIER = 100
EXIT_GROUP_WINDOW = timedelta(seconds=10)
PRICE_DECIMALS = 4


class _OrderFill(NamedTuple):
    """One execution increment of an order: detection time, qty and price of that increment."""

    at: datetime
    order_id: str
    symbol: str
    side: str
    qty: int
    price: float
    reason: str
    metadata: JsonRow


class _Cycle(NamedTuple):
    fills: tuple[_OrderFill, ...]
    open: bool
    oversold: bool = False


class _TickPrices(NamedTuple):
    times: list[datetime]
    prices: list[float]


def build_trades(order_rows: list[JsonRow], tick_rows: list[JsonRow]) -> list[Trade]:
    """Return every round trip in the orders log, ordered by entry time."""
    ticks = _tick_prices(tick_rows)
    fills_by_symbol: dict[str, list[_OrderFill]] = defaultdict(list)
    for fill in _order_fills(order_rows):
        fills_by_symbol[fill.symbol].append(fill)
    trades = [
        _trade(cycle, ticks)
        for fills in fills_by_symbol.values()
        for cycle in _position_cycles(fills)
    ]
    return sorted(trades, key=lambda trade: trade["entry"]["time"])


def _order_fills(order_rows: list[JsonRow]) -> list[_OrderFill]:
    """Return incremental executions, time-ordered; partial_fill qty is cumulative per order."""
    rows_by_order: dict[str, list[tuple[datetime, JsonRow]]] = defaultdict(list)
    for row in order_rows:
        if row.get("action") not in FILL_ACTIONS:
            continue
        at = parse_timestamp(row.get("timestamp"))
        order_id = row.get("client_order_id")
        if at is None or not order_id:
            logger.warning("Skipping fill row without timestamp or order id: %.200s", row)
            continue
        rows_by_order[str(order_id)].append((at, row))
    fills = [
        fill
        for order_id, stamped in rows_by_order.items()
        for fill in _order_increments(order_id, stamped)
    ]
    return sorted(fills, key=lambda fill: fill.at)


def _order_increments(order_id: str, stamped: list[tuple[datetime, JsonRow]]) -> list[_OrderFill]:
    """Turn one order's cumulative fill rows into one fill per quantity increase.

    Each increment's price is the change in cumulative notional over the change
    in cumulative quantity, and its time is the row that reported it.
    """
    final = max(stamped, key=lambda item: (json_int(item[1].get("qty_filled")) or 0, item[0]))[1]
    side, symbol = final.get("side"), final.get("symbol")
    if side not in SIDES or not symbol:
        logger.warning("Skipping order %s: side=%r symbol=%r", order_id, side, symbol)
        return []
    metadata = final.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    reason = str(final.get("reason") or metadata.get("reason") or "")
    increments: list[_OrderFill] = []
    prev_qty, prev_notional = 0, 0.0
    for at, row in sorted(stamped, key=lambda item: item[0]):
        qty = json_int(row.get("qty_filled")) or 0
        price = json_float(row.get("avg_fill_price"))
        if qty <= prev_qty:
            continue
        if price is None:
            logger.warning("Skipping order %s fill row without a price at %s", order_id, at)
            continue
        notional = qty * price
        step_qty = qty - prev_qty
        step_price = (notional - prev_notional) / step_qty
        increments.append(
            _OrderFill(at, order_id, str(symbol), str(side), step_qty, step_price, reason, metadata)
        )
        prev_qty, prev_notional = qty, notional
    if not increments:
        logger.warning(
            "Skipping order %s with unusable fill: qty=%r price=%r",
            order_id,
            final.get("qty_filled"),
            final.get("avg_fill_price"),
        )
    return increments


def _position_cycles(fills: list[_OrderFill]) -> list[_Cycle]:
    """Split one contract's time-ordered fills into flat-to-flat position cycles."""
    cycles: list[_Cycle] = []
    current: list[_OrderFill] = []
    position = 0
    for fill in fills:
        if fill.side == "sell" and position <= 0:
            logger.warning("Skipping sell %s on a flat %s position", fill.order_id, fill.symbol)
            continue
        current.append(fill)
        position += fill.qty if fill.side == "buy" else -fill.qty
        if position < 0:
            logger.warning("Sells exceed buys in %s at %s", fill.symbol, fill.at.isoformat())
        if position <= 0:
            cycles.append(_Cycle(tuple(current), open=False, oversold=position < 0))
            current, position = [], 0
    if current:
        cycles.append(_Cycle(tuple(current), open=True))
    return cycles


def _trade(cycle: _Cycle, ticks: _TickPrices) -> Trade:
    buys = [fill for fill in cycle.fills if fill.side == "buy"]
    sells = [fill for fill in cycle.fills if fill.side == "sell"]
    entry_avg = _weighted_price(buys)
    entry = _fill(buys, entry_avg, json_float(buys[0].metadata.get("spot_price")), "")
    exits = [_exit_fill(group, ticks) for group in _exit_groups(sells)]
    first = buys[0]
    return Trade(
        id=f"{first.symbol}@{first.at:%H:%M:%S}",
        contract=first.symbol,
        direction=str(first.metadata.get("direction") or ""),
        scenario_label=str(first.metadata.get("scenario_label") or ""),
        qty=entry["qty"],
        entry=entry,
        exits=exits,
        realized_pnl=None if cycle.oversold else _realized_pnl(cycle.fills),
        open=cycle.open,
        inventory_incomplete=cycle.oversold,
    )


def _exit_groups(sells: list[_OrderFill]) -> list[list[_OrderFill]]:
    """Group consecutive same-reason sells that belong to one exit decision."""
    groups: list[list[_OrderFill]] = []
    for sell in sells:
        last = groups[-1] if groups else None
        if last and last[0].reason == sell.reason and sell.at - last[0].at <= EXIT_GROUP_WINDOW:
            groups[-1] = [*last, sell]
        else:
            groups.append([sell])
    return groups


def _exit_fill(sells: list[_OrderFill], ticks: _TickPrices) -> Fill:
    underlying = _price_at(ticks, sells[0].at)
    return _fill(sells, _weighted_price(sells), underlying, sells[0].reason)


def _fill(fills: list[_OrderFill], avg_price: float, underlying: float | None, reason: str) -> Fill:
    return Fill(
        time=to_chart_time(fills[0].at),
        underlying_price=underlying,
        option_price=round(avg_price, PRICE_DECIMALS),
        qty=sum(fill.qty for fill in fills),
        reason=reason,
    )


def _weighted_price(fills: list[_OrderFill]) -> float:
    total_qty = sum(fill.qty for fill in fills)
    return sum(fill.price * fill.qty for fill in fills) / total_qty


def _realized_pnl(fills: tuple[_OrderFill, ...]) -> float | None:
    """Realize each sale against the average cost of the contracts held at that time."""
    if not any(fill.side == "sell" for fill in fills):
        return None
    held_qty, held_cost, pnl = 0, 0.0, 0.0
    for fill in fills:
        if fill.side == "buy":
            held_qty, held_cost = held_qty + fill.qty, held_cost + fill.price * fill.qty
            continue
        average_cost = held_cost / held_qty if held_qty > 0 else 0.0
        pnl += (fill.price - average_cost) * fill.qty * CONTRACT_MULTIPLIER
        sold = min(fill.qty, held_qty)
        held_qty, held_cost = held_qty - sold, held_cost - average_cost * sold
    return round(pnl, 2)


def _tick_prices(tick_rows: list[JsonRow]) -> _TickPrices:
    points = [point for point in map(_tick_point, tick_rows) if point is not None]
    points.sort(key=lambda point: point[0])
    return _TickPrices([at for at, _ in points], [price for _, price in points])


def _tick_point(row: JsonRow) -> tuple[datetime, float] | None:
    at = parse_timestamp(row.get("timestamp"))
    price = json_float(row.get("price"))
    return (at, price) if at is not None and price is not None else None


def _price_at(ticks: _TickPrices, at: datetime) -> float | None:
    """Return the price of the latest tick at or before `at`."""
    index = bisect_right(ticks.times, at) - 1
    return ticks.prices[index] if index >= 0 else None
