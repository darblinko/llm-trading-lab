"""Session-type classification and execution parameter overrides.

Classifies the current session into one of four types based on thesis,
regime, and multi-timeframe alignment. Each type carries a frozen
parameter set that downstream modules (profit-taking, entry gate,
LLM cadence) consume instead of hard-coded constants.

Pure function: no module-level state. Called every tick.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SessionType(str, Enum):
    """Broad classification of the current trading session."""

    TREND_DAY = "trend_day"
    BREAKOUT_DAY = "breakout_day"
    RANGE_DAY = "range_day"
    EVENT_DAY = "event_day"


@dataclass(frozen=True)
class SessionTypeParams:
    """Execution parameters driven by session classification."""

    session_type: SessionType
    max_hold_minutes: float
    take_profit_reduce_pct: float
    take_profit_close_pct: float
    entry_gate: int
    reentry_gate: int
    checkin_interval_ticks: int  # LLM check-in cadence (1 tick = 1 minute)


# ---------------------------------------------------------------------------
# Pre-built parameter sets: one per session type
# ---------------------------------------------------------------------------

# Cadence: 5-minute LLM check-ins are the default for all session types.
# Rationale: Opus thesis provides the directional anchor; Haiku check-ins every
# 5 minutes evaluate whether the thesis is still playing out. 1-minute ticks are
# too noisy for decision-making. Emergency triggers (thesis transitions, regime
# changes) bypass this cadence regardless of session type. EVENT_DAY is the one
# exception: high-impact news can move markets faster than 5 min.

_TREND_DAY = SessionTypeParams(
    session_type=SessionType.TREND_DAY,
    max_hold_minutes=120.0,
    take_profit_reduce_pct=1.50,
    take_profit_close_pct=3.00,
    entry_gate=70,
    reentry_gate=60,
    checkin_interval_ticks=5,
)

_BREAKOUT_DAY = SessionTypeParams(
    session_type=SessionType.BREAKOUT_DAY,
    max_hold_minutes=60.0,
    take_profit_reduce_pct=1.00,
    take_profit_close_pct=2.00,
    entry_gate=70,
    reentry_gate=65,
    checkin_interval_ticks=5,
)

_RANGE_DAY = SessionTypeParams(
    session_type=SessionType.RANGE_DAY,
    max_hold_minutes=25.0,
    take_profit_reduce_pct=0.50,
    take_profit_close_pct=1.50,
    entry_gate=80,
    reentry_gate=80,
    checkin_interval_ticks=5,
)

_EVENT_DAY = SessionTypeParams(
    session_type=SessionType.EVENT_DAY,
    max_hold_minutes=15.0,
    take_profit_reduce_pct=0.40,
    take_profit_close_pct=1.00,
    entry_gate=85,
    reentry_gate=85,
    checkin_interval_ticks=1,
)

_PARAMS: dict[SessionType, SessionTypeParams] = {
    SessionType.TREND_DAY: _TREND_DAY,
    SessionType.BREAKOUT_DAY: _BREAKOUT_DAY,
    SessionType.RANGE_DAY: _RANGE_DAY,
    SessionType.EVENT_DAY: _EVENT_DAY,
}

# Regimes considered "trending" for classification purposes, with their direction
_TRENDING_REGIMES = {
    "bull_trend": "bull",
    "strong_bull_trend": "bull",
    "bear_trend": "bear",
    "strong_bear_trend": "bear",
}


def classify_session(
    *,
    thesis_bias: str,
    thesis_confidence: str,
    thesis_state: str,
    regime: str,
    mtf_aligned: bool,
    session_trend_direction: str,
    has_high_impact_events: bool,
    slope_15m: float | None,
) -> SessionTypeParams:
    """Classify the current session and return execution parameters.

    Called every tick. Pure function: no side effects.

    Parameters
    ----------
    thesis_bias : str
        Current thesis bias ("bull", "bear", "neutral").
    thesis_confidence : str
        Current thesis confidence ("high", "medium", "low").
    thesis_state : str
        Thesis health state ("intact", "weakened", "invalidated").
    regime : str
        Current macro regime value (e.g. "strong_bull_trend").
    mtf_aligned : bool
        Whether multi-timeframe alignment confirms regime direction.
    session_trend_direction : str
        Session trend from get_session_trend() ("bull", "bear", "none").
    has_high_impact_events : bool
        Whether high-impact economic events are imminent.
    slope_15m : float | None
        15-minute linear regression slope magnitude.

    Returns
    -------
    SessionTypeParams
        Frozen parameter set for the classified session type.
    """
    # Priority 1: Event day: high-impact events override everything
    if has_high_impact_events:
        return _EVENT_DAY

    regime_direction = _TRENDING_REGIMES.get(regime)
    thesis_intact = thesis_state == "intact"
    thesis_with_regime = thesis_bias in ("bull", "bear") and thesis_bias == regime_direction
    session_with_thesis = session_trend_direction == thesis_bias
    thesis_confident = thesis_confidence in ("high", "medium")
    slope_strong = slope_15m is not None and abs(slope_15m) > 0.2

    # Priority 2: Trend day: thesis, regime and session trend point the same way,
    # with MTF alignment, a confident thesis and a strong slope
    if (
        thesis_intact
        and thesis_with_regime
        and session_with_thesis
        and thesis_confident
        and mtf_aligned
        and slope_strong
    ):
        return _TREND_DAY

    # Priority 3: Breakout day: trending regime in the thesis direction + thesis intact,
    # but session trend, MTF or slope not fully confirmed yet
    if thesis_intact and thesis_with_regime:
        return _BREAKOUT_DAY

    # Priority 4: Range day: everything else
    return _RANGE_DAY


def get_params(session_type: SessionType) -> SessionTypeParams:
    """Look up the parameter set for a session type."""
    return _PARAMS[session_type]
