"""Tests for the daily loss circuit breaker."""

import pytest

from agent_controls.risk import (
    CONSECUTIVE_LOSS_THRESHOLD,
    MAX_TOTAL_LOSERS,
    SIZE_REDUCTION_FACTOR,
    check_circuit_breaker,
    get_risk_summary,
    get_size_multiplier,
    init,
    reset,
    update_after_trade,
)


class TestCircuitBreaker:
    def setup_method(self):
        reset()
        init(10000.0)

    def test_starts_not_halted(self):
        halted, reason = check_circuit_breaker()
        assert halted is False
        assert reason is None

    def test_normal_size_multiplier(self):
        assert get_size_multiplier() == 1.0

    def test_win_resets_consecutive_losses(self):
        update_after_trade(-100)
        update_after_trade(-100)
        update_after_trade(200)  # win resets consecutive count
        assert get_size_multiplier() == 1.0

    def test_consecutive_losses_reduce_size(self):
        for _ in range(CONSECUTIVE_LOSS_THRESHOLD):
            update_after_trade(-100)
        assert get_size_multiplier() == SIZE_REDUCTION_FACTOR

    def test_daily_loss_halts_session(self):
        # 10% of 10000 = 1000 loss
        update_after_trade(-600)
        halted, _ = check_circuit_breaker()
        assert halted is False

        update_after_trade(-500)  # total = -1100, exceeds 10%
        halted, reason = check_circuit_breaker()
        assert halted is True
        assert "10%" in reason or "exceeds" in reason

    def test_total_losers_halts_session(self):
        for i in range(MAX_TOTAL_LOSERS):
            update_after_trade(-50)
            # Win between losses to reset consecutive but not total
            if i < MAX_TOTAL_LOSERS - 1:
                update_after_trade(10)

        halted, reason = check_circuit_breaker()
        assert halted is True
        assert "losing trades" in reason

    def test_halted_size_multiplier_is_zero(self):
        update_after_trade(-1500)  # exceeds 10% immediately
        assert get_size_multiplier() == 0.0

    def test_risk_summary(self):
        update_after_trade(-100)
        update_after_trade(200)
        summary = get_risk_summary()
        assert summary["realized_pnl"] == 100.0
        assert summary["total_wins"] == 1
        assert summary["total_losses"] == 1
        assert summary["consecutive_losses"] == 0
        assert summary["halted"] is False

    def test_zero_equity_is_rejected(self):
        reset()
        with pytest.raises(ValueError, match="starting equity"):
            init(0.0)

    @pytest.mark.parametrize("equity", [-1.0, float("nan"), float("inf")])
    def test_invalid_equity_is_rejected(self, equity):
        reset()
        with pytest.raises(ValueError, match="starting equity"):
            init(equity)

    def test_trade_before_init_is_rejected(self):
        _reset_uninitialized()
        with pytest.raises(RuntimeError, match="init"):
            update_after_trade(-100)

    @pytest.mark.parametrize("pnl", [float("nan"), float("inf"), float("-inf")])
    def test_non_finite_pnl_is_rejected_without_state_change(self, pnl):
        update_after_trade(-100)
        before = get_risk_summary()
        with pytest.raises(ValueError, match="finite"):
            update_after_trade(pnl)
        assert get_risk_summary() == before

    def test_breaker_still_fires_after_rejected_nan(self):
        with pytest.raises(ValueError):
            update_after_trade(float("nan"))
        update_after_trade(-5000)
        halted, reason = check_circuit_breaker()
        assert halted is True
        assert "Daily loss" in reason
        assert get_size_multiplier() == 0.0


def _reset_uninitialized():
    import agent_controls.risk as risk

    risk.reset()
    risk._starting_equity = 0.0
