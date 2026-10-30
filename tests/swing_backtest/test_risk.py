"""Tests for the portfolio risk engine."""

import dataclasses

import pytest

from swing_backtest.config import RiskLimits
from swing_backtest.domain import (
    PortfolioRiskState,
    Position,
    TradeDirection,
)
from swing_backtest.risk import ProposedTrade, RiskEngine


@pytest.fixture
def config() -> RiskLimits:
    return RiskLimits(portfolio_value=1_000_000)


@pytest.fixture
def engine(config: RiskLimits) -> RiskEngine:
    return RiskEngine(config)


@pytest.fixture
def healthy_state() -> PortfolioRiskState:
    return PortfolioRiskState(
        total_premium_at_risk=100_000.0,
        total_portfolio_value=1_000_000.0,
        daily_pnl=-10_000.0,
        positions_by_sector={"Technology": 2, "Healthcare": 1},
        net_delta_exposure=50_000.0,  # dollar delta
        premium_by_expiry_week={"2026-W25": 50_000.0},
    )


@pytest.fixture
def sample_trade() -> ProposedTrade:
    return ProposedTrade(
        ticker="AAPL",
        direction=TradeDirection.CALL,
        premium_cost=25_000.0,
        option_expiry="2026-06-20",
        sector="Technology",
        delta=0.40,
        underlying_price=230.0,
    )


@pytest.fixture
def open_positions() -> list[Position]:
    return [
        Position(
            ticker="NVDA",
            contract_symbol="X",
            direction=TradeDirection.CALL,
            qty=5,
            avg_entry_price=8.0,
            opened_at="2026-05-20T09:46:00Z",
            scenario_id="s1",
            stop_loss_pct=50.0,
            stop_loss_portfolio_pct=2.0,
            profit_target=15.0,
            max_hold_days=30,
            option_expiry="2026-06-20",
        ),
    ]


class TestRiskEngineAllPass:
    def test_healthy_trade_passes(self, engine, sample_trade, healthy_state, open_positions):
        result = engine.check_all(sample_trade, healthy_state, open_positions)
        assert result.passed is True
        assert all(c.passed for c in result.checks)


class TestMaxPositions:
    def test_rejects_at_max(self, engine, sample_trade, healthy_state):
        # Create 20 positions (at max)
        positions = [
            Position(
                ticker=f"T{i}",
                contract_symbol="X",
                direction=TradeDirection.CALL,
                qty=1,
                avg_entry_price=5.0,
                opened_at="2026-01-01T00:00:00Z",
                scenario_id=f"s{i}",
                stop_loss_pct=50.0,
                stop_loss_portfolio_pct=1.0,
                profit_target=10.0,
                max_hold_days=14,
                option_expiry="2026-02-01",
            )
            for i in range(20)
        ]
        result = engine.check_all(sample_trade, healthy_state, positions)
        assert result.passed is False
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "max_positions" for c in failed)


class TestTotalPremium:
    def test_rejects_when_premium_exceeds_limit(self, engine, open_positions):
        # State already at 390k premium, new 25k would push to 415k > 400k limit
        state = PortfolioRiskState(
            total_premium_at_risk=390_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=0.0,
            positions_by_sector={"Technology": 1},
            net_delta_exposure=0.1,
            premium_by_expiry_week={},
        )
        trade = ProposedTrade(
            ticker="MSFT",
            direction=TradeDirection.CALL,
            premium_cost=25_000.0,
            option_expiry="2026-07-01",
            sector="Technology",
            delta=0.35,
            underlying_price=500.0,
        )
        result = engine.check_all(trade, state, open_positions)
        assert result.passed is False
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "total_premium_at_risk" for c in failed)


class TestDailyDrawdown:
    def test_rejects_when_drawdown_exceeds_limit(self, engine, sample_trade, open_positions):
        # Daily PnL is -60k = -6% > -5% limit
        state = PortfolioRiskState(
            total_premium_at_risk=100_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=-60_000.0,
            positions_by_sector={"Technology": 1},
            net_delta_exposure=0.1,
            premium_by_expiry_week={},
        )
        result = engine.check_all(sample_trade, state, open_positions)
        assert result.passed is False
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "daily_drawdown" for c in failed)


class TestSectorConcentration:
    def test_rejects_when_sector_full(self, engine, open_positions):
        state = PortfolioRiskState(
            total_premium_at_risk=100_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=0.0,
            positions_by_sector={"Technology": 4},  # Already at max
            net_delta_exposure=0.1,
            premium_by_expiry_week={},
        )
        trade = ProposedTrade(
            ticker="AAPL",
            direction=TradeDirection.CALL,
            premium_cost=20_000.0,
            option_expiry="2026-07-01",
            sector="Technology",
            delta=0.35,
            underlying_price=230.0,
        )
        result = engine.check_all(trade, state, open_positions)
        assert result.passed is False
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "sector_concentration" for c in failed)


class TestPerPositionSize:
    def test_rejects_oversized_position(self, engine, healthy_state, open_positions):
        # 35k on a 1M portfolio = 3.5% > 3% limit
        trade = ProposedTrade(
            ticker="TSLA",
            direction=TradeDirection.PUT,
            premium_cost=35_000.0,
            option_expiry="2026-07-01",
            sector="Consumer Discretionary",
            delta=-0.40,
            underlying_price=300.0,
        )
        result = engine.check_all(trade, healthy_state, open_positions)
        assert result.passed is False
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "per_position_size" for c in failed)


class TestExpiryConcentration:
    def test_rejects_when_expiry_week_overloaded(self, engine, open_positions):
        state = PortfolioRiskState(
            total_premium_at_risk=100_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=0.0,
            positions_by_sector={"Technology": 1},
            net_delta_exposure=0.0,
            premium_by_expiry_week={"2026-W25": 240_000.0},  # Near 25% already
        )
        trade = ProposedTrade(
            ticker="AAPL",
            direction=TradeDirection.CALL,
            premium_cost=20_000.0,
            option_expiry="2026-06-20",
            sector="Technology",
            delta=0.35,
            underlying_price=230.0,
        )
        result = engine.check_all(trade, state, open_positions)
        assert result.passed is False
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "expiry_concentration" for c in failed)

    def test_different_dates_in_same_iso_week_aggregate(self, engine, open_positions):
        # Existing exposure keyed by week; a proposed expiry on a DIFFERENT
        # date in the SAME ISO week (Mon 2026-06-15 vs Fri 2026-06-19) must
        # hit the same bucket.
        state = PortfolioRiskState(
            total_premium_at_risk=100_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=0.0,
            positions_by_sector={"Technology": 1},
            net_delta_exposure=0.0,
            premium_by_expiry_week={"2026-W25": 240_000.0},
        )
        trade = ProposedTrade(
            ticker="AAPL",
            direction=TradeDirection.CALL,
            premium_cost=20_000.0,
            option_expiry="2026-06-19",
            sector="Technology",
            delta=0.35,
            underlying_price=230.0,
        )
        result = engine.check_all(trade, state, open_positions)
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "expiry_concentration" for c in failed)

    def test_adjacent_week_is_a_separate_bucket(self, engine, open_positions):
        state = PortfolioRiskState(
            total_premium_at_risk=100_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=0.0,
            positions_by_sector={"Technology": 1},
            net_delta_exposure=0.0,
            premium_by_expiry_week={"2026-W25": 240_000.0},
        )
        trade = ProposedTrade(
            ticker="AAPL",
            direction=TradeDirection.CALL,
            premium_cost=20_000.0,
            option_expiry="2026-06-22",  # Mon of W26
            sector="Technology",
            delta=0.35,
            underlying_price=230.0,
        )
        result = engine.check_all(trade, state, open_positions)
        expiry_checks = [c for c in result.checks if c.name == "expiry_concentration"]
        assert expiry_checks[0].passed is True


class TestDirectionalTilt:
    def test_rejects_when_dollar_delta_tilt_exceeds_limit(self, engine, open_positions):
        # 650k existing dollar delta + 0.5 x 100 x 1200 = 60k -> 71% > 70%
        state = PortfolioRiskState(
            total_premium_at_risk=100_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=0.0,
            positions_by_sector={"Technology": 1},
            net_delta_exposure=650_000.0,
            premium_by_expiry_week={},
        )
        trade = ProposedTrade(
            ticker="NVDA",
            direction=TradeDirection.CALL,
            premium_cost=6_000.0,
            option_expiry="2026-08-21",
            sector="Technology",
            delta=0.50,
            underlying_price=1200.0,
        )
        result = engine.check_all(trade, state, open_positions)
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "directional_tilt" for c in failed)

    def test_opposing_put_reduces_tilt(self, engine, open_positions):
        # Same 650k long tilt; a put SUBTRACTS dollar delta -> passes
        state = PortfolioRiskState(
            total_premium_at_risk=100_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=0.0,
            positions_by_sector={"Technology": 1},
            net_delta_exposure=650_000.0,
            premium_by_expiry_week={},
        )
        trade = ProposedTrade(
            ticker="AMZN",
            direction=TradeDirection.PUT,
            premium_cost=6_000.0,
            option_expiry="2026-08-21",
            sector="Consumer Discretionary",
            delta=-0.50,
            underlying_price=1200.0,
        )
        result = engine.check_all(trade, state, open_positions)
        tilt_checks = [c for c in result.checks if c.name == "directional_tilt"]
        assert tilt_checks[0].passed is True


class TestTickerExposure:
    def test_rejects_second_position_on_same_ticker(
        self, engine, sample_trade, healthy_state, open_positions
    ):
        # open_positions holds NVDA
        trade = ProposedTrade(
            ticker="NVDA",
            direction=TradeDirection.PUT,
            premium_cost=5_000.0,
            option_expiry="2026-08-21",
            sector="Technology",
            delta=-0.40,
            underlying_price=1200.0,
        )
        result = engine.check_all(trade, healthy_state, open_positions)
        assert result.passed is False
        failed = [c for c in result.checks if not c.passed]
        assert any(c.name == "ticker_exposure" for c in failed)

    def test_allows_new_ticker(self, engine, sample_trade, healthy_state, open_positions):
        result = engine.check_all(sample_trade, healthy_state, open_positions)
        ticker_checks = [c for c in result.checks if c.name == "ticker_exposure"]
        assert ticker_checks[0].passed is True


class TestInputValidity:
    @staticmethod
    def _state(**changes) -> PortfolioRiskState:
        values = dict(
            total_premium_at_risk=100_000.0,
            total_portfolio_value=1_000_000.0,
            daily_pnl=-10_000.0,
            positions_by_sector={"Technology": 2},
            net_delta_exposure=50_000.0,
            premium_by_expiry_week={"2026-W25": 50_000.0},
        )
        values.update(changes)
        return PortfolioRiskState(**values)

    @staticmethod
    def _failed_names(result) -> set[str]:
        return {c.name for c in result.checks if not c.passed}

    @pytest.mark.parametrize(
        "changes",
        [
            {"daily_pnl": float("nan")},
            {"total_premium_at_risk": float("nan")},
            {"net_delta_exposure": float("inf")},
            {"total_portfolio_value": 0.0},
            {"total_portfolio_value": -1.0},
            {"total_portfolio_value": float("nan")},
            {"premium_by_expiry_week": {"2026-W25": float("nan")}},
        ],
    )
    def test_rejects_invalid_state(self, engine, sample_trade, open_positions, changes):
        result = engine.check_all(sample_trade, self._state(**changes), open_positions)
        assert result.passed is False
        assert "inputs_valid" in self._failed_names(result)

    @pytest.mark.parametrize(
        "changes",
        [
            {"premium_cost": -5_000.0},
            {"premium_cost": 0.0},
            {"premium_cost": float("nan")},
            {"qty": 0},
            {"qty": -2},
            {"delta": float("nan")},
            {"underlying_price": 0.0},
        ],
    )
    def test_rejects_invalid_trade(self, engine, sample_trade, open_positions, changes):
        trade = dataclasses.replace(sample_trade, **changes)
        result = engine.check_all(trade, self._state(), open_positions)
        assert result.passed is False
        assert "inputs_valid" in self._failed_names(result)

    @pytest.mark.parametrize(
        "changes",
        [{"max_daily_drawdown_pct": float("nan")}, {"max_premium_at_risk_pct": -1.0}],
    )
    def test_rejects_invalid_limits(self, sample_trade, open_positions, changes):
        engine = RiskEngine(RiskLimits(portfolio_value=1_000_000, **changes))
        result = engine.check_all(sample_trade, self._state(), open_positions)
        assert result.passed is False
        assert "inputs_valid" in self._failed_names(result)

    def test_valid_inputs_report_a_passing_input_check(
        self, engine, sample_trade, healthy_state, open_positions
    ):
        result = engine.check_all(sample_trade, healthy_state, open_positions)
        assert result.checks[0].name == "inputs_valid"
        assert result.checks[0].passed is True
