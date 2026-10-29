"""Shape of the JSON document served by GET /api/day/<YYYY-MM-DD>.

Every `time` field is chart time (see chart_time.to_chart_time).
"""

from typing import TypedDict


class Point(TypedDict):
    time: int
    value: float


class Bar(TypedDict):
    time: int
    open: float
    high: float
    low: float
    close: float
    volume: float


class Oscillator(TypedDict):
    label: str
    histogram: list[Point]
    lines: dict[str, list[Point]]
    levels: list[float]


class Indicators(TypedDict):
    overlays: dict[str, list[Point]]
    oscillators: dict[str, Oscillator]


class KeyLevel(TypedDict):
    label: str
    price: float
    group: str


class ScenarioEvent(TypedDict):
    time: int
    kind: str
    text: str
    price: float | None


class TriggerZone(TypedDict):
    low: float
    high: float


class Scenario(TypedDict):
    id: str
    label: str
    direction: str
    setup_type: str
    confidence: str
    source: str
    book: str
    created_time: int
    end_time: int | None
    status: str
    terminal_reason: str | None
    ttl_minutes: int | None
    trigger_zone: TriggerZone | None
    target_price: float | None
    invalidation_price: float | None
    invalidation_op: str | None
    trigger_conditions: list[str]
    invalidation_conditions: list[str]
    events: list[ScenarioEvent]
    evaluation_ids: list[str]


class AgentLeg(TypedDict):
    model: str
    decision: str
    reasoning: str
    key_factors: list[str]
    case_for: str
    case_against: str
    verdict: str
    wait_for: str
    latency_ms: int | None
    raw_response: str


class Evaluation(TypedDict):
    id: str
    scenario_id: str | None
    label: str
    time: int
    decision: str
    consensus_reasoning: str
    legs: dict[str, AgentLeg | None]
    link_quality: str
    note: str | None


class Fill(TypedDict):
    time: int
    underlying_price: float | None
    option_price: float
    qty: int
    reason: str


class Trade(TypedDict):
    id: str
    contract: str
    direction: str
    scenario_label: str
    qty: int
    entry: Fill
    exits: list[Fill]
    realized_pnl: float | None
    open: bool


class DayPayload(TypedDict):
    date: str
    is_today: bool
    warnings: list[str]
    bars: list[Bar]
    indicators: Indicators
    key_levels: list[KeyLevel]
    scenarios: list[Scenario]
    evaluations: list[Evaluation]
    trades: list[Trade]
