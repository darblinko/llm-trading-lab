"""Risk limits for the portfolio risk engine, read from RISK_* environment variables."""

import os
from collections.abc import Mapping
from dataclasses import dataclass, fields


@dataclass(frozen=True)
class RiskLimits:
    portfolio_value: float
    max_positions: int = 20
    max_premium_at_risk_pct: float = 40.0
    max_daily_drawdown_pct: float = 5.0
    max_expiry_concentration_pct: float = 25.0
    max_sector_positions: int = 4
    max_directional_tilt_pct: float = 70.0
    max_per_position_risk_pct: float = 3.0

    @classmethod
    def from_env(cls, environ: Mapping[str, str] | None = None) -> "RiskLimits":
        """Build limits from RISK_<FIELD> variables; unset or empty fields keep their defaults.

        RISK_PORTFOLIO_VALUE is required. A value that does not parse raises ValueError.
        """
        env = os.environ if environ is None else environ
        values = {}
        for field in fields(cls):
            raw = env.get(f"RISK_{field.name.upper()}")
            if not raw:
                continue
            caster = int if field.type in (int, "int") else float
            try:
                values[field.name] = caster(raw)
            except ValueError as exc:
                raise ValueError(f"RISK_{field.name.upper()}={raw!r} is not a number") from exc
        if "portfolio_value" not in values:
            raise ValueError("RISK_PORTFOLIO_VALUE is required")
        return cls(**values)
