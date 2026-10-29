"""Records shared by the Stage A price-only backtest of the setup families."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from swing_backtest.domain import TradeDirection

# Entry is blocked when earnings are strictly nearer than this many calendar days.
EARNINGS_WINDOW_DAYS = 7


class ExitReason(str, Enum):
    STOP = "stop"
    TARGET = "target"
    TIME = "time"


class SkipReason(str, Enum):
    NO_ENTRY_BAR = "no_entry_bar"
    EARNINGS_BLOCK = "earnings_block"
    GAP_THROUGH_STOP = "gap_through_stop"
    NO_TARGET_ROOM = "no_target_room"
    RISK_TOO_SMALL = "risk_too_small"
    RISK_TOO_LARGE = "risk_too_large"
    INCOMPLETE_HOLD = "incomplete_hold"
    INVALID_FORWARD_BARS = "invalid_forward_bars"


@dataclass(frozen=True)
class StageAConfig:
    """Entry filters, fixed before any out-of-sample run.

    min_rr matches the live quality gate's reward-to-risk floor. Risk is the
    distance from entry to stop as a percent of entry.
    """

    min_rr: float = 2.0
    min_risk_pct: float = 0.5
    max_risk_pct: float = 15.0
    earnings_window_days: int = EARNINGS_WINDOW_DAYS


@dataclass(frozen=True)
class ExitFill:
    exit_date: date
    exit_price: float
    reason: ExitReason
    bars_held: int


@dataclass(frozen=True)
class TradeResult:
    """One simulated trade. r_multiple is signed: +1 is one unit of initial risk."""

    candidate_id: str
    ticker: str
    family: str
    variant: str
    direction: TradeDirection
    as_of: date
    trigger_date: date
    entry_date: date
    entry_price: float
    stop_price: float
    target_price: float
    exit_date: date
    exit_price: float
    exit_reason: ExitReason
    r_multiple: float
    bars_held: int
    max_hold_bars: int
    context: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True)
class TradeSkip:
    """A candidate that triggered but did not become a trade.

    For INVALID_FORWARD_BARS no trigger scan ran, and trigger_date holds the
    candidate's as_of.
    """

    candidate_id: str
    ticker: str
    family: str
    variant: str
    trigger_date: date
    reason: SkipReason
