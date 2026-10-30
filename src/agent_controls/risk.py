"""Daily realized profit and loss tracking and circuit breaker.

Enforces aggregate risk limits that the per-trade execution gate cannot see:
daily loss limits, consecutive-loser size reduction, and session halt.

Module-level state resets daily via ensure_session().
"""

import logging
import math
from datetime import datetime

logger = logging.getLogger(__name__)

# --- Thresholds ---
MAX_DAILY_LOSS_PCT = 0.10  # Halt if daily loss exceeds 10% of starting equity
MAX_TOTAL_LOSERS = 5  # Halt after 5 losing trades in a day
CONSECUTIVE_LOSS_THRESHOLD = 3  # Reduce size after 3 consecutive losers
SIZE_REDUCTION_FACTOR = 0.5  # Cut size in half when consecutive losses hit


# --- Module-level session state ---
_starting_equity: float = 0.0
_realized_pnl: float = 0.0
_consecutive_losses: int = 0
_total_losses: int = 0
_total_wins: int = 0
_halted: bool = False
_halt_reason: str | None = None
_current_date: str | None = None


def init(starting_equity: float) -> None:
    """Initialize with the account's starting equity for the day.

    Raises:
        ValueError: if starting_equity is not a finite number above zero.
    """
    global _starting_equity
    if not math.isfinite(starting_equity) or starting_equity <= 0:
        raise ValueError(f"starting equity must be finite and above zero, got {starting_equity!r}")
    _starting_equity = starting_equity
    logger.info("Risk tracker initialized: starting equity = %.2f", starting_equity)


def reset() -> None:
    """Reset all risk state for a new session."""
    global _realized_pnl, _consecutive_losses, _total_losses, _total_wins
    global _halted, _halt_reason, _current_date
    _current_date = datetime.now().strftime("%Y-%m-%d")
    _realized_pnl = 0.0
    _consecutive_losses = 0
    _total_losses = 0
    _total_wins = 0
    _halted = False
    _halt_reason = None
    logger.info("Risk tracker reset for %s", _current_date)


def ensure_session() -> None:
    """Reset if the date has changed."""
    today = datetime.now().strftime("%Y-%m-%d")
    if _current_date != today:
        reset()


def update_after_trade(pnl: float) -> None:
    """Update risk state after a trade closes.

    Args:
        pnl: Realized profit or loss in account currency (positive = win, negative = loss).

    Raises:
        RuntimeError: if init() has not set a starting equity.
        ValueError: if pnl is not finite. State is left unchanged.
    """
    global _realized_pnl, _consecutive_losses, _total_losses, _total_wins
    global _halted, _halt_reason

    if _starting_equity <= 0:
        raise RuntimeError("call init() with the starting equity before recording trades")
    if not math.isfinite(pnl):
        raise ValueError(f"pnl must be finite, got {pnl!r}")

    _realized_pnl += pnl

    if pnl < 0:
        _consecutive_losses += 1
        _total_losses += 1
        logger.info(
            "Risk: loss %.2f (consecutive=%d, total_losses=%d, daily_pnl=%.2f)",
            pnl,
            _consecutive_losses,
            _total_losses,
            _realized_pnl,
        )
    else:
        _consecutive_losses = 0
        _total_wins += 1
        logger.info(
            "Risk: win %.2f (total_wins=%d, daily_pnl=%.2f)", pnl, _total_wins, _realized_pnl
        )

    # Check halt conditions
    if _realized_pnl < 0 and -_realized_pnl / _starting_equity >= MAX_DAILY_LOSS_PCT:
        _halted = True
        _halt_reason = (
            f"Daily loss {_realized_pnl:.2f} exceeds {MAX_DAILY_LOSS_PCT:.0%} of starting equity"
        )
        logger.warning("CIRCUIT BREAKER: %s", _halt_reason)

    if _total_losses >= MAX_TOTAL_LOSERS:
        _halted = True
        _halt_reason = f"{_total_losses} losing trades today: session halted"
        logger.warning("CIRCUIT BREAKER: %s", _halt_reason)


def check_circuit_breaker() -> tuple[bool, str | None]:
    """Check if trading should be halted.

    Returns:
        (halted, reason): if halted is True, no new trades should be entered.
    """
    return _halted, _halt_reason


def get_size_multiplier() -> float:
    """Return position size multiplier based on risk state.

    Returns 0.5 after CONSECUTIVE_LOSS_THRESHOLD consecutive losses,
    1.0 otherwise. Returns 0.0 if halted.
    """
    if _halted:
        return 0.0
    if _consecutive_losses >= CONSECUTIVE_LOSS_THRESHOLD:
        return SIZE_REDUCTION_FACTOR
    return 1.0


def get_risk_summary() -> dict:
    """Return current risk state for logging/display."""
    return {
        "starting_equity": _starting_equity,
        "realized_pnl": round(_realized_pnl, 2),
        "consecutive_losses": _consecutive_losses,
        "total_losses": _total_losses,
        "total_wins": _total_wins,
        "halted": _halted,
        "halt_reason": _halt_reason,
        "size_multiplier": get_size_multiplier(),
    }
