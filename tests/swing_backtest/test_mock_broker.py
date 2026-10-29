"""Tests for MockBroker fill simulation and position sizing."""

import pytest

from swing_backtest.mock_broker import BacktestConfig, MockBroker


@pytest.fixture
def default_config() -> BacktestConfig:
    return BacktestConfig()


@pytest.fixture
def broker(default_config: BacktestConfig) -> MockBroker:
    return MockBroker(default_config)


class TestSimulateEntry:
    def test_entry_applies_positive_slippage(self, broker: MockBroker) -> None:
        fill = broker.simulate_entry(100.0, 10)
        assert fill.price > 100.0

    def test_entry_slippage_matches_config(self, broker: MockBroker) -> None:
        fill = broker.simulate_entry(100.0, 10)
        expected_slippage = 100.0 * 0.005  # 0.5%
        assert fill.slippage == pytest.approx(expected_slippage)
        assert fill.price == pytest.approx(100.0 + expected_slippage)

    def test_entry_commission_per_contract(self, broker: MockBroker) -> None:
        fill = broker.simulate_entry(100.0, 5)
        assert fill.commission == pytest.approx(0.65 * 5)

    def test_entry_qty_preserved(self, broker: MockBroker) -> None:
        fill = broker.simulate_entry(50.0, 7)
        assert fill.qty == 7

    def test_entry_total_cost(self, broker: MockBroker) -> None:
        fill = broker.simulate_entry(100.0, 10)
        expected = fill.price * 10 + fill.commission
        assert fill.total_cost == pytest.approx(expected)

    def test_entry_with_custom_config(self) -> None:
        config = BacktestConfig(slippage_pct=1.0, commission_per_contract=1.50)
        broker = MockBroker(config)
        fill = broker.simulate_entry(200.0, 3)
        assert fill.slippage == pytest.approx(2.0)
        assert fill.price == pytest.approx(202.0)
        assert fill.commission == pytest.approx(4.50)


class TestSimulateExit:
    def test_exit_applies_negative_slippage(self, broker: MockBroker) -> None:
        fill = broker.simulate_exit(100.0, 10)
        assert fill.price < 100.0

    def test_exit_slippage_matches_config(self, broker: MockBroker) -> None:
        fill = broker.simulate_exit(100.0, 10)
        expected_slippage = 100.0 * 0.005
        assert fill.slippage == pytest.approx(expected_slippage)
        assert fill.price == pytest.approx(100.0 - expected_slippage)

    def test_exit_commission(self, broker: MockBroker) -> None:
        fill = broker.simulate_exit(100.0, 4)
        assert fill.commission == pytest.approx(0.65 * 4)

    def test_exit_qty_preserved(self, broker: MockBroker) -> None:
        fill = broker.simulate_exit(80.0, 12)
        assert fill.qty == 12


class TestComputePositionSize:
    def test_basic_position_size(self, broker: MockBroker) -> None:
        # 3% of 1M = 30K, at 100 per contract = 300 contracts
        qty = broker.compute_position_size(1_000_000.0, 100.0)
        assert qty == 300

    def test_position_size_rounds_down(self, broker: MockBroker) -> None:
        # 3% of 100K = 3K, at 7 per contract = 428.57 -> 428
        qty = broker.compute_position_size(100_000.0, 7.0)
        assert qty == 428

    def test_zero_price_returns_zero(self, broker: MockBroker) -> None:
        qty = broker.compute_position_size(1_000_000.0, 0.0)
        assert qty == 0

    def test_negative_price_returns_zero(self, broker: MockBroker) -> None:
        qty = broker.compute_position_size(1_000_000.0, -10.0)
        assert qty == 0

    def test_insufficient_capital(self) -> None:
        config = BacktestConfig(per_position_pct=3.0)
        broker = MockBroker(config)
        # 3% of 10 = 0.30, at 100 per contract = 0
        qty = broker.compute_position_size(10.0, 100.0)
        assert qty == 0

    def test_custom_per_position_pct(self) -> None:
        config = BacktestConfig(per_position_pct=5.0)
        broker = MockBroker(config)
        # 5% of 1M = 50K, at 100 = 500
        qty = broker.compute_position_size(1_000_000.0, 100.0)
        assert qty == 500
