"""Portfolio-level risk engine. ALL checks must pass before order submission."""

import math
from dataclasses import dataclass, fields
from datetime import date
from numbers import Integral, Real

from swing_backtest.config import RiskLimits
from swing_backtest.domain import (
    PortfolioRiskState,
    Position,
    RiskCheck,
    RiskCheckResult,
    TradeDirection,
)


def expiry_week_key(iso_date: str) -> str:
    """ISO-week bucket for an expiry date, e.g. '2026-06-19' -> '2026-W25'.

    Both the risk engine and the risk-state builder must use this so
    different expiry dates in the same week share one concentration bucket.
    """
    iso = date.fromisoformat(iso_date[:10]).isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


@dataclass(frozen=True)
class ProposedTrade:
    """A proposed trade to be evaluated by the risk engine."""

    ticker: str
    direction: TradeDirection
    premium_cost: float  # Total cost in dollars
    option_expiry: str  # ISO date
    sector: str  # GICS sector
    delta: float  # Signed delta (+calls, -puts)
    underlying_price: float  # For dollar-delta tilt
    qty: int = 1


class RiskEngine:
    """Portfolio-level risk checks. ALL must pass before order submission."""

    def __init__(self, config: RiskLimits):
        self.config = config

    def check_all(
        self,
        proposed: ProposedTrade,
        state: PortfolioRiskState,
        open_positions: list[Position],
    ) -> RiskCheckResult:
        """Run all risk checks against the proposed trade.

        open_positions and state both include unfilled entry orders (as
        provisional positions), so an order that has not filled still counts
        toward max_positions, ticker exposure and the state-based limits.
        """
        input_check = self._check_inputs(proposed, state)
        if not input_check.passed:
            return RiskCheckResult(passed=False, checks=(input_check,))
        checks = (
            input_check,
            self._check_max_positions(open_positions),
            self._check_total_premium(proposed, state),
            self._check_daily_drawdown(state),
            self._check_expiry_concentration(proposed, state),
            self._check_sector_concentration(proposed, state),
            self._check_directional_tilt(proposed, state),
            self._check_per_position_size(proposed, state),
            self._check_ticker_exposure(proposed, open_positions),
        )
        return RiskCheckResult(
            passed=all(c.passed for c in checks),
            checks=checks,
        )

    def _check_inputs(self, proposed: ProposedTrade, state: PortfolioRiskState) -> RiskCheck:
        # NaN compares false against every limit, so missing data would otherwise pass.
        problems = [*_limit_problems(self.config), *_state_problems(state)]
        problems += _trade_problems(proposed)
        return RiskCheck(
            name="inputs_valid",
            passed=not problems,
            detail="; ".join(problems) if problems else "state, limits and trade are valid",
        )

    def _check_max_positions(self, open_positions: list[Position]) -> RiskCheck:
        count = len(open_positions)
        passed = count < self.config.max_positions
        return RiskCheck(
            name="max_positions",
            passed=passed,
            detail=f"{count}/{self.config.max_positions} positions",
        )

    def _check_total_premium(self, proposed: ProposedTrade, state: PortfolioRiskState) -> RiskCheck:
        new_total = state.total_premium_at_risk + proposed.premium_cost
        limit = state.total_portfolio_value * (self.config.max_premium_at_risk_pct / 100)
        passed = new_total <= limit
        return RiskCheck(
            name="total_premium_at_risk",
            passed=passed,
            detail=f"{new_total:.0f} / {limit:.0f} ({self.config.max_premium_at_risk_pct}%)",
        )

    def _check_daily_drawdown(self, state: PortfolioRiskState) -> RiskCheck:
        drawdown_pct = (
            abs(state.daily_pnl) / state.total_portfolio_value * 100 if state.daily_pnl < 0 else 0.0
        )
        passed = drawdown_pct < self.config.max_daily_drawdown_pct
        return RiskCheck(
            name="daily_drawdown",
            passed=passed,
            detail=f"{drawdown_pct:.2f}% / {self.config.max_daily_drawdown_pct}% max",
        )

    def _check_expiry_concentration(
        self, proposed: ProposedTrade, state: PortfolioRiskState
    ) -> RiskCheck:
        expiry_week = expiry_week_key(proposed.option_expiry)
        current_in_week = state.premium_by_expiry_week.get(expiry_week, 0.0)
        new_total = current_in_week + proposed.premium_cost
        limit = state.total_portfolio_value * (self.config.max_expiry_concentration_pct / 100)
        passed = new_total <= limit
        return RiskCheck(
            name="expiry_concentration",
            passed=passed,
            detail=f"{new_total:.0f} in week {expiry_week} / {limit:.0f} limit",
        )

    def _check_sector_concentration(
        self, proposed: ProposedTrade, state: PortfolioRiskState
    ) -> RiskCheck:
        current_in_sector = state.positions_by_sector.get(proposed.sector, 0)
        new_count = current_in_sector + 1
        passed = new_count <= self.config.max_sector_positions
        return RiskCheck(
            name="sector_concentration",
            passed=passed,
            detail=f"{new_count}/{self.config.max_sector_positions} in {proposed.sector}",
        )

    def _check_directional_tilt(
        self, proposed: ProposedTrade, state: PortfolioRiskState
    ) -> RiskCheck:
        # Dollar delta: delta x 100 shares x underlying price x contracts.
        # state.net_delta_exposure is already in dollar-delta terms.
        proposed_dollar_delta = proposed.delta * 100 * proposed.underlying_price * proposed.qty
        new_dollar_delta = state.net_delta_exposure + proposed_dollar_delta
        tilt_pct = abs(new_dollar_delta) / state.total_portfolio_value * 100
        passed = tilt_pct <= self.config.max_directional_tilt_pct
        return RiskCheck(
            name="directional_tilt",
            passed=passed,
            detail=f"{tilt_pct:.1f}% net directional / {self.config.max_directional_tilt_pct}% max",
        )

    def _check_per_position_size(
        self, proposed: ProposedTrade, state: PortfolioRiskState
    ) -> RiskCheck:
        risk_pct = proposed.premium_cost / state.total_portfolio_value * 100
        passed = risk_pct <= self.config.max_per_position_risk_pct
        return RiskCheck(
            name="per_position_size",
            passed=passed,
            detail=f"{risk_pct:.2f}% / {self.config.max_per_position_risk_pct}% max",
        )

    def _check_ticker_exposure(
        self, proposed: ProposedTrade, open_positions: list[Position]
    ) -> RiskCheck:
        held = sorted({p.ticker for p in open_positions})
        passed = proposed.ticker not in held
        return RiskCheck(
            name="ticker_exposure",
            passed=passed,
            detail=(
                f"no open position on {proposed.ticker}"
                if passed
                else f"already holding {proposed.ticker}"
            ),
        )


def _is_finite_number(value: object) -> bool:
    return isinstance(value, Real) and not isinstance(value, bool) and math.isfinite(value)


def _limit_problems(config: RiskLimits) -> list[str]:
    return [
        f"limit {field.name} must be a finite nonnegative number"
        for field in fields(config)
        if not _is_finite_number(getattr(config, field.name)) or getattr(config, field.name) < 0
    ]


def _state_problems(state: PortfolioRiskState) -> list[str]:
    problems = [
        f"state {name} must be finite"
        for name in ("total_premium_at_risk", "daily_pnl", "net_delta_exposure")
        if not _is_finite_number(getattr(state, name))
    ]
    if not _is_finite_number(state.total_portfolio_value) or state.total_portfolio_value <= 0:
        problems.append("state total_portfolio_value must be finite and positive")
    if _is_finite_number(state.total_premium_at_risk) and state.total_premium_at_risk < 0:
        problems.append("state total_premium_at_risk must be nonnegative")
    for week, premium in state.premium_by_expiry_week.items():
        if not _is_finite_number(premium) or premium < 0:
            problems.append(f"state premium for {week} must be finite and nonnegative")
    for sector, count in state.positions_by_sector.items():
        if not isinstance(count, Integral) or isinstance(count, bool) or count < 0:
            problems.append(f"state position count for {sector} must be a nonnegative integer")
    return problems


def _trade_problems(proposed: ProposedTrade) -> list[str]:
    problems = []
    if not _is_finite_number(proposed.premium_cost) or proposed.premium_cost <= 0:
        problems.append("trade premium_cost must be finite and positive")
    if not isinstance(proposed.qty, Integral) or isinstance(proposed.qty, bool) or proposed.qty < 1:
        problems.append("trade qty must be a positive integer")
    if not _is_finite_number(proposed.delta):
        problems.append("trade delta must be finite")
    if not _is_finite_number(proposed.underlying_price) or proposed.underlying_price <= 0:
        problems.append("trade underlying_price must be finite and positive")
    return problems
