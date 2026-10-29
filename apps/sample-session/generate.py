#!/usr/bin/env python3
"""Write one synthetic trading session in the log layout that both review apps read.

Usage: python3 generate.py [--out DIR]

Prices come from a seeded random walk. Scenario levels are derived from that walk so
that each lifecycle (creation, trigger, evaluation, fill, exit or expiry) is consistent
with the chart. Agent responses are fixed placeholder strings. Nothing is copied from a
recorded session. Two runs write byte-identical files.
"""

from __future__ import annotations

import argparse
import json
import random
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
SEED = 20260107
SYMBOL = "QQQ"
INSTANCE = "claude"
SESSION_DAY = date(2026, 1, 7)
WARM_UP_DAYS = (date(2026, 1, 5), date(2026, 1, 6))
START_PRICE = 100.0
OPEN, CLOSE = time(9, 30), time(16, 0)
PREMARKET_START = time(8, 0)
BAR_SECONDS = 180
FIRST_TICK = time(9, 30, 40)
TICK_COUNT = 130
CONTRACT_MULTIPLIER = 100
MODELS = {"opus": "synthetic-opus", "astra": "synthetic-astra"}


@dataclass(frozen=True)
class Bar:
    start: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int


def at(day: date, clock: str) -> datetime:
    return datetime.combine(day, time.fromisoformat(clock), ET)


def iso(stamp: datetime) -> str:
    return stamp.isoformat(timespec="seconds")


def session_drift(minute_of_day: int) -> float:
    """Per-minute drift on the session day: morning rally, midday fade, afternoon recovery."""
    for start, end, drift in ((585, 660, 0.00012), (690, 765, -0.0001), (825, 900, 0.0001)):
        if start <= minute_of_day < end:
            return drift
    return 0.0


def volume_for(minute_of_day: int, rng: random.Random) -> int:
    if minute_of_day < 570:
        return int(3000 * rng.uniform(0.5, 1.5))
    distance = abs(minute_of_day - 765) / 195
    return int((20000 + 40000 * distance**2) * rng.uniform(0.6, 1.4))


def make_bar(start: datetime, open_price: float, ret: float, rng: random.Random) -> Bar:
    close = open_price * (1 + ret)
    high = max(open_price, close) * (1 + abs(rng.gauss(0, 0.0002)))
    low = min(open_price, close) * (1 - abs(rng.gauss(0, 0.0002)))
    o, c = round(open_price, 2), round(close, 2)
    minute_of_day = start.hour * 60 + start.minute
    return Bar(
        start,
        o,
        max(round(high, 2), o, c),
        min(round(low, 2), o, c),
        c,
        volume_for(minute_of_day, rng),
    )


def minute_bars(rng: random.Random) -> list[Bar]:
    """RTH minute bars for the warm-up days, plus premarket and RTH for the session day."""
    bars: list[Bar] = []
    price = START_PRICE
    for day in (*WARM_UP_DAYS, SESSION_DAY):
        first = PREMARKET_START if day == SESSION_DAY else OPEN
        stamp, end = datetime.combine(day, first, ET), datetime.combine(day, CLOSE, ET)
        price *= 1 + rng.gauss(0, 0.003)
        while stamp < end:
            minute_of_day = stamp.hour * 60 + stamp.minute
            drift = session_drift(minute_of_day) if day == SESSION_DAY else 0.0
            bar = make_bar(stamp, price, rng.gauss(drift, 0.0005), rng)
            bars.append(bar)
            price = bar.close
            stamp += timedelta(minutes=1)
    return bars


def is_rth(bar: Bar) -> bool:
    return OPEN <= bar.start.time() < CLOSE


def three_minute_bars(bars: list[Bar]) -> list[Bar]:
    groups: dict[datetime, list[Bar]] = {}
    for bar in filter(is_rth, bars):
        bucket = bar.start - timedelta(minutes=bar.start.minute % 3)
        groups.setdefault(bucket, []).append(bar)
    return [
        Bar(
            start,
            group[0].open,
            max(b.high for b in group),
            min(b.low for b in group),
            group[-1].close,
            sum(b.volume for b in group),
        )
        for start, group in sorted(groups.items())
    ]


def ema(values: list[float], length: int) -> list[float]:
    alpha, result = 2 / (length + 1), []
    for value in values:
        result.append(value if not result else alpha * value + (1 - alpha) * result[-1])
    return result


def sma(values: list[float | None], length: int) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        window = values[max(0, index - length + 1) : index + 1]
        usable = [v for v in window if v is not None]
        result.append(sum(usable) / length if len(usable) == length else None)
    return result


def rsi(closes: list[float], length: int = 14) -> list[float | None]:
    """Wilder RSI; None until `length` changes are available."""
    result: list[float | None] = [None]
    gain = loss = 0.0
    for index in range(1, len(closes)):
        change = closes[index] - closes[index - 1]
        up, down = max(change, 0.0), max(-change, 0.0)
        if index <= length:
            gain, loss = gain + up / length, loss + down / length
        else:
            gain, loss = (gain * (length - 1) + up) / length, (loss * (length - 1) + down) / length
        ready = index >= length
        result.append(
            100 - 100 / (1 + gain / loss) if ready and loss else (100.0 if ready else None)
        )
    return result


def stochastic(values: list[float | None], length: int = 14) -> list[float | None]:
    result: list[float | None] = []
    for index in range(len(values)):
        window = values[max(0, index - length + 1) : index + 1]
        if len(window) < length or None in window:
            result.append(None)
            continue
        low, high = min(window), max(window)
        result.append(100 * (values[index] - low) / (high - low) if high > low else 50.0)
    return result


def indicator_table(bars_3m: list[Bar]) -> list[dict[str, float | None]]:
    """One row of indicator values per completed 3-minute bar."""
    closes = [bar.close for bar in bars_3m]
    volumes = [float(bar.volume) for bar in bars_3m]
    macd = [fast - slow for fast, slow in zip(ema(closes, 12), ema(closes, 26), strict=True)]
    signal = ema(macd, 9)
    rsi_values = rsi(closes)
    stoch_k = sma(stochastic(rsi_values), 3)
    stoch_d = sma(stoch_k, 3)
    ema_9, ema_21 = ema(closes, 9), ema(closes, 21)
    rows = []
    for index in range(len(bars_3m)):
        prior = volumes[max(0, index - 10) : index]
        signed = [
            b.volume if b.close >= b.open else -b.volume
            for b in bars_3m[max(0, index - 20) : index + 1]
        ]
        rows.append(
            {
                "rsi": rounded(rsi_values[index], 2),
                "stochrsi_k": rounded(stoch_k[index], 2),
                "stochrsi_d": rounded(stoch_d[index], 2),
                "macd_hist": round(macd[index] - signal[index], 4),
                "rvol": round(volumes[index] / (sum(prior) / len(prior)), 2)
                if len(prior) == 10
                else None,
                "cvd_21": sum(signed),
                "ema_9": round(ema_9[index], 2),
                "ema_21": round(ema_21[index], 2),
            }
        )
    return rows


def rounded(value: float | None, digits: int) -> float | None:
    return None if value is None else round(value, digits)


@dataclass(frozen=True)
class Market:
    minutes: list[Bar]
    bars_3m: list[Bar]
    indicators: list[dict[str, float | None]]

    def session_minutes(self) -> list[Bar]:
        return [b for b in self.minutes if b.start.date() == SESSION_DAY and is_rth(b)]

    def price_at(self, stamp: datetime) -> float:
        """Close of the latest minute bar that started at or before `stamp`."""
        return [b for b in self.minutes if b.start <= stamp][-1].close

    def high_low(self, start: datetime, end: datetime) -> tuple[float, float]:
        window = [b for b in self.minutes if start <= b.start < end]
        return max(b.high for b in window), min(b.low for b in window)


def daily_levels(market: Market) -> dict[str, float]:
    prior = [b for b in market.minutes if b.start.date() == WARM_UP_DAYS[-1]]
    high, low, close = max(b.high for b in prior), min(b.low for b in prior), prior[-1].close
    span = (high - low) * 1.1
    on_high, on_low = market.high_low(at(SESSION_DAY, "08:00"), at(SESSION_DAY, "09:30"))
    return {
        "prev_day_high": high,
        "prev_day_low": low,
        "prev_day_close": close,
        "overnight_high": on_high,
        "overnight_low": on_low,
        "d_h4": round(close + span / 2, 2),
        "d_h3": round(close + span / 4, 2),
        "d_pivot": round((high + low + close) / 3, 2),
        "d_l3": round(close - span / 4, 2),
        "d_l4": round(close - span / 2, 2),
    }


def tick_rows(market: Market) -> list[dict]:
    levels = daily_levels(market)
    or_high, or_low = market.high_low(at(SESSION_DAY, "09:30"), at(SESSION_DAY, "09:45"))
    rows = []
    for index in range(TICK_COUNT):
        stamp = at(SESSION_DAY, FIRST_TICK.isoformat()) + timedelta(seconds=index * BAR_SECONDS)
        completed = [
            i
            for i, b in enumerate(market.bars_3m)
            if b.start + timedelta(seconds=BAR_SECONDS) <= stamp
        ]
        opening_range_done = stamp.time() >= time(9, 45)
        rows.append(
            {
                "tick": index + 1,
                "timestamp": iso(stamp),
                "symbol": SYMBOL,
                "price": market.price_at(stamp),
                "vwap": session_vwap(market, stamp),
                **market.indicators[completed[-1]],
                **levels,
                "opening_range_high": or_high if opening_range_done else None,
                "opening_range_low": or_low if opening_range_done else None,
            }
        )
    return rows


def session_vwap(market: Market, stamp: datetime) -> float:
    bars = [b for b in market.session_minutes() if b.start <= stamp]
    weighted = sum((b.high + b.low + b.close) / 3 * b.volume for b in bars)
    return round(weighted / sum(b.volume for b in bars), 2)


def build_market() -> Market:
    minutes = minute_bars(random.Random(SEED))
    bars_3m = three_minute_bars(minutes)
    return Market(minutes, bars_3m, indicator_table(bars_3m))


# Session records: scenarios, orders and agent traces.

SYSTEM_PROMPT = "Synthetic system prompt placeholder."
DEADLINE = time(15, 45)


@dataclass(frozen=True)
class Tick:
    number: int
    at: datetime
    price: float
    row: dict


@dataclass
class Records:
    scenarios: list[dict]
    orders: list[dict]
    traces: list[tuple[datetime, str]]


@dataclass(frozen=True)
class Setup:
    label: str
    direction: str
    setup_type: str
    confidence: str
    source: str
    ttl_minutes: int
    zone: tuple[float, float]
    target: float
    stop: float


def as_ticks(rows: list[dict]) -> list[Tick]:
    return [Tick(r["tick"], datetime.fromisoformat(r["timestamp"]), r["price"], r) for r in rows]


def tick_at(ticks: list[Tick], clock: str) -> Tick:
    return next(t for t in ticks if t.at.time() >= time.fromisoformat(clock))


def first_tick(ticks: list[Tick], after: Tick, test) -> Tick:
    found = next((t for t in ticks if t.number > after.number and test(t)), None)
    if found is None:
        raise RuntimeError(f"no tick after #{after.number} meets the scenario condition")
    return found


def scenario_row(setup: Setup, at: datetime, status: str, price: float, **extra) -> dict:
    row = {
        "event_timestamp": iso(at),
        "label": setup.label,
        "status": status,
        "source": setup.source,
    }
    if status == "created":
        row |= {
            "direction": setup.direction,
            "setup_type": setup.setup_type,
            "confidence": setup.confidence,
            "ttl_minutes": setup.ttl_minutes,
            "trigger_zone": {"low": setup.zone[0], "high": setup.zone[1]},
            "target_price": setup.target,
            "trigger_conditions": [
                f"price >= {setup.zone[0]}"
                if setup.direction == "call"
                else f"price <= {setup.zone[1]}"
            ],
            "invalidation_conditions": [
                f"price < {setup.stop}" if setup.direction == "call" else f"price > {setup.stop}"
            ],
        }
    return row | extra | {"snapshot_at_event": {"price": price}}


def leg_response(decision: str, reasoning: str) -> dict:
    return {
        "decision": decision,
        "reasoning": reasoning,
        "key_factors": ["Synthetic factor: price position against the trigger zone"],
        "case_for": "Synthetic case for.",
        "case_against": "Synthetic case against.",
        "verdict": f"Synthetic verdict: {decision}.",
        "wait_for": "",
    }


def fenced(summary: str, body: str) -> list[str]:
    return [
        "<details>",
        f"<summary>{summary} ({len(body)} chars)</summary>",
        "",
        "```",
        body,
        "```",
        "</details>",
        "",
    ]


def trace_call(
    tick: Tick, kind: str, at: datetime, latency_ms: int, model: str, human: str, response: dict
) -> str:
    body = json.dumps(response, indent=2)
    return "\n".join(
        [
            f"### Tick #{tick.number} | {kind} | {at:%H:%M:%S} | {latency_ms}ms",
            "",
            f"**Model**: `{model}`",
            "",
            *fenced("System prompt", SYSTEM_PROMPT),
            *fenced("Human message", human),
            "**Response**:",
            "```json",
            body,
            "```",
            "",
            f"**Parsed result** ({kind.split(':')[0]}):",
            "```json",
            body,
            "```",
            "",
            "---",
            "",
            "",
        ]
    )


def trace_event(tick: Tick, kind: str, at: datetime, text: str) -> str:
    return "\n".join(
        [f"### Tick #{tick.number} | {kind} | {at:%H:%M:%S}", "", text, "", "---", "", ""]
    )


def entry_timing(records: Records, setup: Setup, tick: Tick, votes: dict[str, str]) -> datetime:
    """Log one two-agent consensus call; return the time both legs returned."""
    reasons = {
        name: f"Synthetic response: {vote}, {VOTE_TEXT[vote]}" for name, vote in votes.items()
    }
    ballot = ", ".join(f"{name}={vote}" for name, vote in votes.items())
    unanimous = len(set(votes.values())) == 1
    decision = votes["opus"] if unanimous else "wait"
    headline = f"{HEADLINES[decision] if unanimous else 'No consensus'} ({ballot})."
    joined = " | ".join(f"{name}: {text}" for name, text in reasons.items())
    records.scenarios.append(
        scenario_row(
            setup,
            tick.at,
            "entry_timing",
            tick.price,
            decision=decision,
            reasoning=f"{headline} {joined}",
            bull_case=" | ".join(f"{name}: Synthetic case for." for name in votes),
            bear_case=" | ".join(f"{name}: Synthetic case against." for name in votes),
            verdict=f"{headline} "
            + " | ".join(f"{n}: Synthetic verdict: {v}." for n, v in votes.items()),
        )
    )
    returned = tick.at + timedelta(seconds=34 + tick.number % 20)
    human = (
        f"## Triggered Scenario\nLabel: {setup.label}\nDirection: {setup.direction}\n"
        f"Price: {tick.price}\nSynthetic prompt: answer enter_now, wait or pass."
    )
    for offset, (name, vote) in enumerate(votes.items()):
        latency = 1800 + 400 * offset + tick.number * 7
        records.traces.append(
            (
                returned,
                trace_call(
                    tick,
                    f"entry_timing:{name}",
                    returned,
                    latency,
                    MODELS[name],
                    human,
                    leg_response(vote, reasons[name]),
                ),
            )
        )
    return returned


VOTE_TEXT = {
    "enter_now": "trigger zone reached and no conflict found.",
    "wait": "no trigger met yet.",
    "pass": "setup no longer fits the session.",
}
HEADLINES = {"enter_now": "Unanimous enter", "pass": "Unanimous pass", "wait": "No consensus"}


def contract(setup: Setup, price: float) -> str:
    kind = "C" if setup.direction == "call" else "P"
    return f"{SYMBOL}{SESSION_DAY:%y%m%d}{kind}{round(price) * 1000:08d}"


def order_rows(
    order_id: str,
    side: str,
    symbol: str,
    at: datetime,
    fills: list[tuple[int, float]],
    reason: str,
    metadata: dict,
) -> list[dict]:
    """A submit row, then one row per cumulative fill update (partial fills first)."""
    total = fills[-1][0]
    base = {
        "client_order_id": order_id,
        "broker_order_id": f"synthetic-{order_id}",
        "symbol": symbol,
        "side": side,
        "qty": total,
        "reason": reason,
        "metadata": metadata,
    }
    rows = [{"timestamp": iso(at), "action": "submit", "status": "new", **base}]
    for step, (cumulative, average) in enumerate(fills, start=1):
        done = cumulative == total
        rows.append(
            {
                "timestamp": iso(at + timedelta(seconds=3 * step)),
                "action": "fill" if done else "partial_fill",
                "status": "filled" if done else "partially_filled",
                "qty_filled": cumulative,
                "avg_fill_price": average,
                **base,
            }
        )
    return rows


def exit_tick(ticks: list[Tick], entry: Tick, setup: Setup, deadline: datetime) -> tuple[Tick, str]:
    """First tick after entry that reaches the target or the stop, else the first tick past
    the deadline (scenario TTL or the session time stop, whichever is earlier)."""
    for tick in ticks:
        if tick.number <= entry.number:
            continue
        if tick.at >= deadline:
            return tick, "time"
        if tick.price >= setup.target:
            return tick, "target"
        if tick.price < setup.stop:
            return tick, "stop"
    raise RuntimeError("session ended before the time stop")


EXIT_REASONS = {
    "target": "Target reached",
    "stop": "Invalidation level broken",
    "time": "Time stop or scenario TTL",
}


def trade(
    records: Records,
    ticks: list[Tick],
    setup: Setup,
    signal: Tick,
    decided: datetime,
    entry_fills: list[tuple[int, float]],
    number: int,
    created: datetime,
) -> str:
    """Buy after a unanimous enter, sell the whole position at the first exit condition and
    return which condition it was."""
    symbol = contract(setup, signal.price)
    metadata = {
        "direction": setup.direction,
        "scenario_label": setup.label,
        "spot_price": signal.price,
        "reason": "Entry",
    }
    records.orders += order_rows(
        f"b{number}", "buy", symbol, decided + timedelta(seconds=2), entry_fills, "", metadata
    )
    deadline = min(
        created + timedelta(minutes=setup.ttl_minutes), datetime.combine(SESSION_DAY, DEADLINE, ET)
    )
    leave, kind = exit_tick(ticks, signal, setup, deadline)
    qty, entry_price = entry_fills[-1]
    exit_price = round(max(0.05, entry_price + 0.5 * (leave.price - signal.price)), 2)
    sold_at = leave.at + timedelta(seconds=20)
    records.orders += order_rows(
        f"s{number}",
        "sell",
        symbol,
        sold_at,
        [(qty, exit_price)],
        EXIT_REASONS[kind],
        {"scenario_label": setup.label},
    )
    records.traces.append(
        (
            sold_at + timedelta(seconds=3),
            trace_event(
                leave,
                "EXIT FILL",
                sold_at + timedelta(seconds=3),
                f"Synthetic exit fill: {qty} x {symbol} at {exit_price} ({EXIT_REASONS[kind]}).",
            ),
        )
    )
    if kind == "stop":
        records.scenarios.append(
            scenario_row(
                setup, leave.at, "invalidated", leave.price, reason=f"price < {setup.stop}"
            )
        )
    return kind


def thesis_call(records: Records, tick: Tick, kind: str, setups: list[Setup]) -> datetime:
    """Log the thesis model call and return when its scenarios were written."""
    at = tick.at + timedelta(seconds=12)
    names = ", ".join(s.label for s in setups)
    response = {
        "scenarios": [s.label for s in setups],
        "summary": f"Synthetic response: {len(setups)} scenario(s) proposed.",
    }
    records.traces.append(
        (
            at,
            trace_call(
                tick,
                kind,
                at,
                2400 + tick.number,
                MODELS["opus"],
                f"Synthetic prompt: propose scenarios. ({names})",
                response,
            ),
        )
    )
    created = at + timedelta(seconds=1)
    for setup in setups:
        records.scenarios.append(scenario_row(setup, created, "created", tick.price))
    return created


def expire(records: Records, ticks: list[Tick], setup: Setup, created: datetime) -> None:
    at = created + timedelta(minutes=setup.ttl_minutes)
    price = [t for t in ticks if t.at <= at][-1].price
    records.scenarios.append(scenario_row(setup, at, "expired", price, reason="TTL elapsed"))


def opening_range_breakout(records: Records, ticks: list[Tick]) -> None:
    """Scenario 1: initial thesis, breakout call, unanimous enter, one fill per side."""
    created_tick = tick_at(ticks, "09:45:00")
    or_high, or_low = (
        created_tick.row["opening_range_high"],
        created_tick.row["opening_range_low"],
    )
    signal = first_tick(ticks, created_tick, lambda t: t.price >= or_high)
    setup = Setup(
        "Opening range breakout",
        "call",
        "breakout",
        "medium",
        "initial_thesis",
        180,
        (or_high, round(or_high + 0.2, 2)),
        round(signal.price + 0.6, 2),
        or_low,
    )
    created = thesis_call(records, created_tick, "thesis_generation", [setup])
    records.scenarios.append(scenario_row(setup, signal.at, "triggered", signal.price))
    decided = entry_timing(records, setup, signal, {"opus": "enter_now", "astra": "enter_now"})
    if trade(records, ticks, setup, signal, decided, [(4, 1.2)], 1, created) != "stop":
        expire(records, ticks, setup, created)


def midday_fade(records: Records, ticks: list[Tick]) -> None:
    """Scenario 2: refresh, put fade, split vote, a gated pass with no model call, then expiry."""
    created_tick = tick_at(ticks, "11:30:00")
    signal = tick_at(ticks, "11:45:00")
    zone = (round(signal.price - 0.1, 2), round(signal.price + 0.1, 2))
    setup = Setup(
        "Midday VWAP fade",
        "put",
        "fade",
        "low",
        "thesis_refresh",
        90,
        zone,
        round(signal.price - 0.5, 2),
        round(signal.price + 0.4, 2),
    )
    created = thesis_call(records, created_tick, "thesis_refresh", [setup])
    records.scenarios.append(scenario_row(setup, signal.at, "triggered", signal.price))
    entry_timing(records, setup, signal, {"opus": "wait", "astra": "pass"})
    gated = tick_at(ticks, "12:03:00")
    records.scenarios.append(
        scenario_row(
            setup,
            gated.at,
            "entry_timing",
            gated.price,
            decision="pass",
            reasoning="Synthetic gate check: pass before any model call, filter not met.",
        )
    )
    expire(records, ticks, setup, created)


def afternoon_reclaim(records: Records, ticks: list[Tick]) -> None:
    """Scenario 3: refresh, call, unanimous enter with a partial entry fill."""
    created_tick = tick_at(ticks, "13:30:00")
    signal = tick_at(ticks, "13:45:00")
    setup = Setup(
        "Afternoon VWAP reclaim",
        "call",
        "reclaim",
        "medium",
        "thesis_refresh",
        120,
        (round(signal.price - 0.15, 2), round(signal.price + 0.05, 2)),
        round(signal.price + 0.4, 2),
        round(signal.price - 0.35, 2),
    )
    created = thesis_call(records, created_tick, "thesis_refresh", [setup])
    records.scenarios.append(scenario_row(setup, signal.at, "triggered", signal.price))
    decided = entry_timing(records, setup, signal, {"opus": "enter_now", "astra": "enter_now"})
    if trade(records, ticks, setup, signal, decided, [(3, 0.95), (6, 0.97)], 2, created) != "stop":
        expire(records, ticks, setup, created)


THESIS = """# Daily thesis {day}

Synthetic thesis for the sample session. Prices are a seeded random walk.

- Opening range breakout: call above the opening range high.
- Midday VWAP fade: put near session VWAP (added by a refresh).
- Afternoon VWAP reclaim: call after a reclaim of session VWAP (added by a refresh).
"""


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def write_outputs(out: Path, market: Market, tick_list: list[dict], records: Records) -> None:
    day = SESSION_DAY.isoformat()
    logs = out / "logs" / INSTANCE
    write_jsonl(logs / "ticks" / f"ticks_{day}.jsonl", tick_list)
    write_jsonl(
        logs / "scenarios" / f"scenarios_{day}.jsonl",
        sorted(records.scenarios, key=lambda r: r["event_timestamp"]),
    )
    write_jsonl(
        logs / "orders" / f"orders_{day}.jsonl",
        sorted(records.orders, key=lambda r: r["timestamp"]),
    )
    trace = logs / "traces" / f"trace_{day}.md"
    trace.parent.mkdir(parents=True, exist_ok=True)
    entries = sorted(records.traces, key=lambda entry: entry[0])
    trace.write_text(f"# Trace {day}\n\n" + "".join(text for _, text in entries))
    thesis = logs / "daily_thesis" / f"thesis_{day}.md"
    thesis.parent.mkdir(parents=True, exist_ok=True)
    thesis.write_text(THESIS.format(day=day))
    session_3m = [b for b in market.bars_3m if b.start.date() == SESSION_DAY]
    snapshot = {
        "produced_at_et": f"{day}T16:00:00",
        "today_bars": [
            {
                "ts": b.start.replace(tzinfo=None).isoformat(),
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
            }
            for b in session_3m
        ],
    }
    (out / "logs" / "shared").mkdir(parents=True, exist_ok=True)
    (out / "logs" / "shared" / "snapshot.json").write_text(json.dumps(snapshot) + "\n")
    write_jsonl(
        out / "market" / f"{SYMBOL}_1m.jsonl",
        [
            {"t": iso(b.start), "o": b.open, "h": b.high, "l": b.low, "c": b.close, "v": b.volume}
            for b in market.minutes
            if is_rth(b)
        ],
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    market = build_market()
    tick_list = tick_rows(market)
    ticks = as_ticks(tick_list)
    records = Records([], [], [])
    for build in (opening_range_breakout, midday_fade, afternoon_reclaim):
        build(records, ticks)
    write_outputs(args.out, market, tick_list, records)
    print(
        f"Wrote {len(tick_list)} ticks, {len(records.scenarios)} scenario rows, "
        f"{len(records.orders)} order rows to {args.out}"
    )


if __name__ == "__main__":
    main()
