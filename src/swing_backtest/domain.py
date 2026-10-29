"""Domain types shared by the risk engine and the backtest."""

from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType


class TradeDirection(str, Enum):
    CALL = "call"
    PUT = "put"


@dataclass(frozen=True)
class Position:
    """An open options position."""

    ticker: str
    contract_symbol: str
    direction: TradeDirection
    qty: int
    avg_entry_price: float
    opened_at: str  # ISO datetime
    scenario_id: str
    stop_loss_pct: float
    stop_loss_portfolio_pct: float
    profit_target: float
    max_hold_days: int
    option_expiry: str  # ISO date
    peak_mid_seen: float = 0.0
    sector: str = ""
    entry_delta: float = 0.0
    underlying_entry_price: float = 0.0
    underlying_stop: float | None = None
    underlying_target: float | None = None
    setup_id: str | None = None
    thesis_stop: float | None = None
    thesis_invalidation: float | None = None


@dataclass(frozen=True)
class PortfolioRiskState:
    """Snapshot of current portfolio risk metrics."""

    total_premium_at_risk: float
    total_portfolio_value: float
    daily_pnl: float
    positions_by_sector: Mapping[str, int]
    net_delta_exposure: float
    premium_by_expiry_week: Mapping[str, float]

    def __post_init__(self) -> None:
        # Copy, then expose read-only views so a caller's later dict mutation cannot leak in.
        object.__setattr__(
            self, "positions_by_sector", MappingProxyType(dict(self.positions_by_sector))
        )
        object.__setattr__(
            self,
            "premium_by_expiry_week",
            MappingProxyType(dict(self.premium_by_expiry_week)),
        )


@dataclass(frozen=True)
class RiskCheck:
    """Result of a single risk check."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class RiskCheckResult:
    """Aggregate result of all risk checks."""

    passed: bool
    checks: tuple[RiskCheck, ...]
