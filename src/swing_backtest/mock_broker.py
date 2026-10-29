"""Simulated broker for backtesting.

Handles fill simulation with slippage and commission,
position sizing, and exit fills.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class BacktestConfig:
    """Fill and sizing assumptions for the simulated broker."""

    initial_capital: float = 1_000_000.0
    max_positions: int = 20
    per_position_pct: float = 3.0
    slippage_pct: float = 0.5
    commission_per_contract: float = 0.65


@dataclass(frozen=True)
class SimulatedFill:
    """Result of a simulated order fill."""

    price: float
    qty: int
    slippage: float
    commission: float

    @property
    def total_cost(self) -> float:
        return self.price * self.qty + self.commission


class MockBroker:
    """Simulated broker that applies slippage and commission to fills."""

    def __init__(self, config: BacktestConfig) -> None:
        self._config = config

    def simulate_entry(self, close_price: float, qty: int) -> SimulatedFill:
        """Simulate entry fill at close + slippage (buying costs more)."""
        slippage = close_price * (self._config.slippage_pct / 100.0)
        fill_price = close_price + slippage
        commission = self._config.commission_per_contract * qty
        return SimulatedFill(
            price=fill_price,
            qty=qty,
            slippage=slippage,
            commission=commission,
        )

    def simulate_exit(self, close_price: float, qty: int) -> SimulatedFill:
        """Simulate exit fill at close - slippage (selling gets less)."""
        slippage = close_price * (self._config.slippage_pct / 100.0)
        fill_price = close_price - slippage
        commission = self._config.commission_per_contract * qty
        return SimulatedFill(
            price=fill_price,
            qty=qty,
            slippage=slippage,
            commission=commission,
        )

    def compute_position_size(self, capital: float, price: float) -> int:
        """Compute qty based on per_position_pct of capital.

        Args:
            capital: Current available capital.
            price: Estimated entry price per contract.

        Returns:
            Number of contracts to buy (at least 1 if capital allows).
        """
        if price <= 0:
            return 0
        allocation = capital * (self._config.per_position_pct / 100.0)
        qty = int(allocation / price)
        return max(qty, 0)
