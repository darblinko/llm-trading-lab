"""Deterministic macro regime classification with hysteresis.

Computes a continuous bull/bear score from snapshot indicators and maps it
to a discrete macro regime.  Hysteresis prevents oscillation: the regime
only changes when the score crosses a boundary for N consecutive bars.
"""

from dataclasses import dataclass
from enum import Enum
from typing import Any

# --- Regime labels ---


class MacroRegime(str, Enum):
    STRONG_BULL_TREND = "strong_bull_trend"
    BULL_TREND = "bull_trend"
    NEUTRAL = "neutral"
    BEAR_TREND = "bear_trend"
    STRONG_BEAR_TREND = "strong_bear_trend"


class MicroRegime(str, Enum):
    IMPULSE = "impulse"
    PULLBACK = "pullback"
    CONSOLIDATION = "consolidation"
    EXHAUSTION = "exhaustion"


# --- Score boundaries (symmetric) ---
# Score is a weighted sum centered at 0.  Positive = bullish, negative = bearish.
#   score > STRONG_THRESHOLD   -> strong_bull_trend
#   score > TREND_THRESHOLD    -> bull_trend
#   score > -TREND_THRESHOLD   -> neutral
#   score > -STRONG_THRESHOLD  -> bear_trend
#   else                       -> strong_bear_trend

STRONG_THRESHOLD = 60  # enter STRONG from a weaker regime
STRONG_EXIT_THRESHOLD = 50  # exit STRONG back to regular TREND (asymmetric)
TREND_THRESHOLD = 25  # enter TREND from NEUTRAL
TREND_EXIT_THRESHOLD = 15  # exit TREND back to NEUTRAL (asymmetric)
HYSTERESIS_BARS = 3


@dataclass(frozen=True)
class RegimeResult:
    regime: MacroRegime
    score: float
    held_bars: int  # how many bars the pending regime has been waiting


# --- Module-level session state ---
_current_regime: MacroRegime = MacroRegime.NEUTRAL
_pending_regime: MacroRegime | None = None
_pending_count: int = 0
_current_date: str | None = None

# --- Regime oscillation tracking ---
_regime_change_timestamps: list[float] = []  # monotonic timestamps of confirmed regime changes
_total_regime_changes: int = 0  # total changes this session

# --- Session trend tracking ---
_session_open_price: float | None = None
_bars_above_vwap: int = 0
_total_bars: int = 0


def reset() -> None:
    """Reset regime state for a new session."""
    global _current_regime, _pending_regime, _pending_count, _current_date
    global _regime_change_timestamps, _total_regime_changes
    global _session_open_price, _bars_above_vwap, _total_bars
    from datetime import datetime

    _current_date = datetime.now().strftime("%Y-%m-%d")
    _current_regime = MacroRegime.NEUTRAL
    _pending_regime = None
    _pending_count = 0
    _regime_change_timestamps = []
    _total_regime_changes = 0
    _session_open_price = None
    _bars_above_vwap = 0
    _total_bars = 0


def ensure_session() -> None:
    """Reset if the date has changed."""
    from datetime import datetime

    today = datetime.now().strftime("%Y-%m-%d")
    if _current_date != today:
        reset()


def _compute_score(snapshot: dict[str, Any], vwap_persistence: int) -> float:
    """Compute a continuous bull/bear score from snapshot indicators.

    Score is centered at 0.  Positive = bullish, negative = bearish.
    Range is roughly -100 to +100.

    Args:
        snapshot: Current indicator snapshot from build_snapshot().
        vwap_persistence: Count of last 10 bars with price above VWAP
            (0 = all below, 10 = all above).
    """
    score = 0.0

    # EMA 9/21 relationship (intraday signal, reduced: ML shows low predictive value): -10 to +10
    ema_9_above_21 = snapshot.get("ema_9_above_21")
    ema_9_21_spread = snapshot.get("ema_9_21_spread", 0) or 0
    if ema_9_above_21 is True:
        score += 5 + min(5, abs(ema_9_21_spread) * 3)
    elif ema_9_above_21 is False:
        score -= 5 + min(5, abs(ema_9_21_spread) * 3)

    # EMA 100/200 structural trend (boosted; ML top feature at longer horizons): -25 to +25
    ema_100_above_200 = snapshot.get("ema_100_above_200")
    ema_100_slope = snapshot.get("ema_100_slope5", 0) or 0
    ema_200_slope = snapshot.get("ema_200_slope5", 0) or 0
    if ema_100_above_200 is True:
        score += 15
        if ema_100_slope > 0:
            score += 5
        if ema_200_slope > 0:
            score += 5
    elif ema_100_above_200 is False:
        score -= 15
        if ema_100_slope < 0:
            score -= 5
        if ema_200_slope < 0:
            score -= 5

    # LinReg slope agreement: emphasis on LinReg 100 (ML top feature): -20 to +20
    short_slopes = [snapshot.get("linreg_slope_10"), snapshot.get("linreg_slope_20")]
    long_slopes = [snapshot.get("linreg_slope_50"), snapshot.get("linreg_slope_100")]
    short_avg = _safe_avg(short_slopes)
    long_avg = _safe_avg(long_slopes)
    linreg_100 = snapshot.get("linreg_slope_100", 0) or 0

    if short_avg > 0 and long_avg > 0:
        score += 10
        if abs(short_avg) > abs(long_avg):
            score += 5  # accelerating
    elif short_avg < 0 and long_avg < 0:
        score -= 10
        if abs(short_avg) > abs(long_avg):
            score -= 5
    # LinReg 100 standalone bonus (ML top feature)
    if linreg_100 > 0:
        score += 5
    elif linreg_100 < 0:
        score -= 5

    # VWAP position: -15 to +15
    vwap_dist = snapshot.get("vwap_dist_pct", 0) or 0
    if vwap_dist > 0:
        score += min(10, vwap_dist * 10)
    else:
        score += max(-10, vwap_dist * 10)

    # VWAP persistence (how consistently price has been above/below): -10 to +10
    # vwap_persistence is 0-10 (bars above VWAP out of last 10)
    score += (vwap_persistence - 5) * 2

    # MACD momentum (reduced; ML shows low predictive value): -5 to +5
    macd_delta = snapshot.get("macd_hist_delta", 0) or 0
    macd_hist = snapshot.get("macd_hist", 0) or 0
    if macd_hist > 0 and macd_delta > 0:
        score += 5
    elif macd_hist > 0:
        score += 2
    elif macd_hist < 0 and macd_delta < 0:
        score -= 5
    elif macd_hist < 0:
        score -= 2

    return score


def _safe_avg(values: list[float | None]) -> float:
    """Average of non-None values, or 0."""
    valid = [v for v in values if v is not None]
    return sum(valid) / len(valid) if valid else 0.0


def _score_to_regime(score: float, current: MacroRegime) -> MacroRegime:
    """Map a continuous score to a regime label with asymmetric exit hysteresis.

    Entering a trend requires crossing the wide threshold (TREND_THRESHOLD=25);
    exiting back toward NEUTRAL requires dropping below the narrow threshold
    (TREND_EXIT_THRESHOLD=15). The band in between is a "hold current regime"
    zone that prevents flapping on narrow-range days without delaying
    legitimate trend-to-opposite-trend transitions.

    The same asymmetry applies at the STRONG boundary (STRONG_THRESHOLD=60 to
    enter, STRONG_EXIT_THRESHOLD=50 to exit).
    """
    if current in (MacroRegime.BULL_TREND, MacroRegime.STRONG_BULL_TREND):
        # Currently bull: use wide thresholds on the way down
        if current == MacroRegime.STRONG_BULL_TREND and score > STRONG_EXIT_THRESHOLD:
            return MacroRegime.STRONG_BULL_TREND
        if score > STRONG_THRESHOLD:
            return MacroRegime.STRONG_BULL_TREND
        if score > TREND_EXIT_THRESHOLD:
            return MacroRegime.BULL_TREND
        if score > -TREND_THRESHOLD:
            return MacroRegime.NEUTRAL
        if score > -STRONG_THRESHOLD:
            return MacroRegime.BEAR_TREND
        return MacroRegime.STRONG_BEAR_TREND

    if current in (MacroRegime.BEAR_TREND, MacroRegime.STRONG_BEAR_TREND):
        # Symmetric for bear
        if current == MacroRegime.STRONG_BEAR_TREND and score < -STRONG_EXIT_THRESHOLD:
            return MacroRegime.STRONG_BEAR_TREND
        if score < -STRONG_THRESHOLD:
            return MacroRegime.STRONG_BEAR_TREND
        if score < -TREND_EXIT_THRESHOLD:
            return MacroRegime.BEAR_TREND
        if score < TREND_THRESHOLD:
            return MacroRegime.NEUTRAL
        if score < STRONG_THRESHOLD:
            return MacroRegime.BULL_TREND
        return MacroRegime.STRONG_BULL_TREND

    # NEUTRAL (or any other): use standard entry thresholds
    if score > STRONG_THRESHOLD:
        return MacroRegime.STRONG_BULL_TREND
    if score > TREND_THRESHOLD:
        return MacroRegime.BULL_TREND
    if score > -TREND_THRESHOLD:
        return MacroRegime.NEUTRAL
    if score > -STRONG_THRESHOLD:
        return MacroRegime.BEAR_TREND
    return MacroRegime.STRONG_BEAR_TREND


def compute_macro_regime(
    snapshot: dict[str, Any],
    vwap_persistence: int = 5,
) -> RegimeResult:
    """Compute the current macro regime with hysteresis.

    Call once per tick.  The regime only transitions when the new regime
    has been signaled for HYSTERESIS_BARS consecutive bars.

    Args:
        snapshot: Current indicator snapshot.
        vwap_persistence: Bars above VWAP out of last 10 (0-10).

    Returns:
        RegimeResult with current regime, score, and pending bar count.
    """
    global _current_regime, _pending_regime, _pending_count
    global _regime_change_timestamps, _total_regime_changes
    global _session_open_price, _bars_above_vwap, _total_bars

    import time as _time

    score = _compute_score(snapshot, vwap_persistence)
    raw_regime = _score_to_regime(score, _current_regime)

    # Track session trend data
    price = snapshot.get("price")
    if price is not None and _session_open_price is None:
        _session_open_price = price
    _total_bars += 1
    if snapshot.get("price_above_vwap"):
        _bars_above_vwap += 1

    if raw_regime != _current_regime:
        if raw_regime == _pending_regime:
            _pending_count += 1
        else:
            _pending_regime = raw_regime
            _pending_count = 1

        if _pending_count >= HYSTERESIS_BARS:
            _current_regime = raw_regime
            _pending_regime = None
            _pending_count = 0
            # Record this confirmed regime change
            _regime_change_timestamps.append(_time.monotonic())
            _total_regime_changes += 1
    else:
        _pending_regime = None
        _pending_count = 0

    return RegimeResult(
        regime=_current_regime,
        score=score,
        held_bars=_pending_count,
    )


def get_current_regime() -> MacroRegime:
    """Return the current macro regime without recomputing."""
    return _current_regime


# --- Regime oscillation detection ---

OSCILLATION_WINDOW_SEC = 90 * 60  # 90 minutes
OSCILLATION_THRESHOLD = 5  # regime changes within window to trigger


def get_regime_oscillation_count(window_sec: float = OSCILLATION_WINDOW_SEC) -> int:
    """Count confirmed regime changes within the last `window_sec` seconds."""
    import time as _time

    now = _time.monotonic()
    cutoff = now - window_sec
    return sum(1 for ts in _regime_change_timestamps if ts >= cutoff)


def is_regime_oscillating() -> bool:
    """True if regime has changed >= OSCILLATION_THRESHOLD times in the window."""
    return get_regime_oscillation_count() >= OSCILLATION_THRESHOLD


def get_total_regime_changes() -> int:
    """Total confirmed regime changes this session."""
    return _total_regime_changes


# --- Session trend detection ---

SESSION_TREND_ATR_FACTOR = 0.5  # price must move > factor * ATR from open
SESSION_TREND_VWAP_PCT = 0.65  # fraction of bars on one side of VWAP


@dataclass(frozen=True)
class SessionTrend:
    direction: str  # "bull", "bear", or "none"
    move_from_open: float  # signed distance from session open
    vwap_consistency: float  # fraction of bars above VWAP (0-1)


def get_session_trend(snapshot: dict[str, Any]) -> SessionTrend:
    """Detect a session-level trend from price action since open.

    A session trend is confirmed when:
    - Price has moved > SESSION_TREND_ATR_FACTOR * ATR from session open
    - Price has been on one side of VWAP for > SESSION_TREND_VWAP_PCT of bars

    Args:
        snapshot: Current indicator snapshot (needs 'price' and 'atr_14' or similar).
    """
    price = snapshot.get("price")
    if price is None or _session_open_price is None or _total_bars < 10:
        return SessionTrend(direction="none", move_from_open=0.0, vwap_consistency=0.5)

    move = price - _session_open_price
    atr = snapshot.get("atr_14") or snapshot.get("daily_atr_14") or 10.0
    threshold = atr * SESSION_TREND_ATR_FACTOR

    vwap_pct = _bars_above_vwap / _total_bars if _total_bars > 0 else 0.5

    direction = "none"
    if move > threshold and vwap_pct >= SESSION_TREND_VWAP_PCT:
        direction = "bull"
    elif move < -threshold and vwap_pct <= (1 - SESSION_TREND_VWAP_PCT):
        direction = "bear"

    return SessionTrend(
        direction=direction,
        move_from_open=move,
        vwap_consistency=vwap_pct,
    )
