import pytest

from swing_backtest.config import RiskLimits


def test_from_env_reads_values_and_keeps_defaults():
    limits = RiskLimits.from_env({"RISK_PORTFOLIO_VALUE": "250000", "RISK_MAX_POSITIONS": "5"})
    assert limits.portfolio_value == 250_000.0
    assert limits.max_positions == 5
    assert limits.max_daily_drawdown_pct == RiskLimits(portfolio_value=1).max_daily_drawdown_pct


def test_from_env_treats_empty_values_as_unset():
    limits = RiskLimits.from_env({"RISK_PORTFOLIO_VALUE": "1000", "RISK_MAX_POSITIONS": ""})
    assert limits.max_positions == 20


def test_from_env_requires_portfolio_value():
    with pytest.raises(ValueError, match="RISK_PORTFOLIO_VALUE is required"):
        RiskLimits.from_env({"RISK_PORTFOLIO_VALUE": ""})


def test_from_env_rejects_unparseable_values():
    with pytest.raises(ValueError, match="RISK_MAX_POSITIONS"):
        RiskLimits.from_env({"RISK_PORTFOLIO_VALUE": "1000", "RISK_MAX_POSITIONS": "five"})
