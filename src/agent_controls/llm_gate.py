"""LLM invocation pre-filter gate.

Decides whether the LangGraph agent (2 Haiku calls per tick) should be
invoked for a given tick. When trigger conditions are absent, the gate
short-circuits to HOLD without making any LLM calls.

Design principles:
  - Pure function: takes a snapshot + context, returns a decision. No module state.
  - Conservative: any doubt triggers invocation. The gate's job is to skip
    obviously-routine ticks, not to make trading decisions.
  - Transparent: always returns a reason string for logging/auditing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# ---------------------------------------------------------------------------
# Gate thresholds (tuned to "call LLM only when something is decision-worthy")
# ---------------------------------------------------------------------------

# Deterministic conviction threshold: 10 points below the 80-point entry gate, the band
# in which a setup is worth an LLM check. Raised from 60 to 70 after a scoring change
# (delta signals and multi-timeframe bonuses) lifted baseline scores.
CONVICTION_WATCH_THRESHOLD = 70

# Strong-conviction threshold: always invoke regardless of other conditions.
# At this level the entry gate is within easy reach and we want the LLM's judgment.
CONVICTION_STRONG_THRESHOLD = 80

# ML probability thresholds for a non-trivial directional bias. The training window had a
# strong upward drift, so bearish outputs are treated with more caution than bullish ones
# until the model is re-validated on a period without that drift.
ML_BULL_THRESHOLD = 0.58
ML_BEAR_THRESHOLD = 0.42

# Regime transition window: how recent a regime change counts as "just changed".
# Only the exact transition tick invokes automatically; subsequent ticks need
# another signal (new conviction level, ML edge, structural event) to justify
# the LLM call. Lowered from 2 to 0 after a replay showed that fresh-window triggers
# made up most invocations while carrying no new information.
REGIME_CHANGE_WINDOW_TICKS = 0


@dataclass(frozen=True)
class GateDecision:
    """Result of a pre-filter evaluation."""

    invoke: bool
    reason: str
    # Categorical trigger tags for audit/reporting. Empty when invoke=False.
    triggers: tuple[str, ...] = ()
    # True when the gate wanted to invoke but was suppressed by check-in cadence.
    # Set by the caller (the live tick loop), not by should_invoke_agent().
    cadence_suppressed: bool = False


# ---------------------------------------------------------------------------
# Emergency-trigger detection (bypasses cadence suppression)
# ---------------------------------------------------------------------------

# Exact-match emergency tags. These are emitted as bare strings by
# should_invoke_agent (e.g., f"thesis_{thesis_state}" where state is
# "weakened" or "invalidated").
_EMERGENCY_EXACT: frozenset[str] = frozenset(
    {
        "thesis_weakened",
        "thesis_invalidated",
    }
)

# Prefix-match emergency tags. These are emitted with a trailing detail
# suffix, so we match on the prefix plus underscore to avoid picking up
# unrelated triggers that merely contain the prefix as a substring.
# Example: "regime_change_bull_trend_to_strong_bull_trend" matches the
# "regime_change_" prefix, but a hypothetical "regime_changed_later" would
# not (it starts with "regime_changed_", missing the underscore after
# "change").
_EMERGENCY_PREFIX: tuple[str, ...] = ("regime_change_",)


def is_emergency_trigger(gate: GateDecision) -> bool:
    """Return True when any trigger in ``gate`` is an emergency that must
    bypass check-in cadence suppression.

    Emergencies reflect structural changes (thesis break, regime flip) that
    require immediate LLM attention: a 5-minute cadence delay could mean
    holding a losing position through a thesis break or missing the entry
    on a regime-change trend day.

    Matching rules:
      - Tags in ``_EMERGENCY_EXACT`` must match the trigger string exactly.
      - Tags in ``_EMERGENCY_PREFIX`` are compared with ``startswith`` and
        already include the trailing underscore, so ``"regime_change_"``
        matches ``"regime_change_bull_to_bear"`` but not ``"regime_changed_later"``.
    """
    for trigger in gate.triggers:
        if trigger in _EMERGENCY_EXACT:
            return True
        for prefix in _EMERGENCY_PREFIX:
            if trigger.startswith(prefix):
                return True
    return False


# Conviction-strong entry trigger prefix.  Used by
# ``is_high_conviction_entry`` to detect cadence-bypass eligibility.
_CONVICTION_STRONG_PREFIX = "conviction_strong_"


def is_high_conviction_entry(gate: GateDecision, has_position: bool) -> bool:
    """Return True when a high-conviction entry signal should bypass cadence.

    On 0DTE options, a 1-4 minute cadence delay on a strong entry signal
    (conv >= 80) costs meaningful entry price.  When the bot is flat (no
    open position), these signals should invoke the LLM immediately rather
    than waiting for the next scheduled check-in.

    When a position IS open, cadence is preserved: the 5-minute cadence
    prevents repeated EXIT decisions on consecutive ticks.
    """
    if has_position:
        return False
    return any(t.startswith(_CONVICTION_STRONG_PREFIX) for t in gate.triggers)


@dataclass(frozen=True)
class PrevTickContext:
    """State from the previous tick(s) needed for change detection.

    Callers maintain this across ticks and pass a fresh snapshot each call.
    Everything is optional so the first tick "just works."
    """

    regime: str | None = None  # previous confirmed macro regime
    tl_breakout: str | None = None  # previous tl_breakout value
    squeeze_state: str | None = None  # previous squeeze_state value
    pullback_signal: str | None = None  # previous pullback_signal value
    session_trend_direction: str | None = None  # previous session trend dir
    thesis_state: str | None = None  # previous thesis health state
    ticks_since_regime_change: int = 999  # how many ticks ago the regime last changed


def should_invoke_agent(
    snapshot: dict[str, Any],
    conviction_score_deterministic: int,
    ml_probability: float | None,
    regime: str,
    positions: list[dict[str, Any]],
    session_trend_direction: str,
    thesis_state: str | None,
    prev: PrevTickContext | None = None,
) -> GateDecision:
    """Decide whether to invoke the LangGraph agent this tick.

    Args:
        snapshot: Current indicator snapshot from build_snapshot().
        conviction_score_deterministic: Raw deterministic conviction score (0-100),
            NOT the ensemble score (we want the pre-ML side for the gate decision
            so the gate is consistent whether or not ML signal is available).
        ml_probability: XGBoost probability (0-1) from XGBMultiHorizon, or None
            if ML signal is disabled or models are missing.
        regime: Current confirmed macro regime string.
        positions: List of open positions (broker-side). Non-empty = position exists.
        session_trend_direction: "bull" / "bear" / "none" from get_session_trend().
        thesis_state: "intact" / "weakened" / "invalidated" / None.
        prev: Previous tick context for change detection. None = first tick.

    Returns:
        GateDecision with invoke=True/False, reason string, and trigger tags.
    """
    triggers: list[str] = []
    # "Weak" triggers don't invoke on their own but do when combined with
    # a conviction_watch (70-79). Kept separate so the gate stays strict.
    weak_triggers: list[str] = []

    # ----- Trigger 1: Open position (must monitor for exits) -----
    if positions:
        triggers.append("position_open")

    # ----- Trigger 2: High conviction candidate -----
    # Strong conviction (>=80) = always invoke (entry-ready).
    # Watch conviction (70-79) = invoke only if corroborated by another signal.
    is_watch = conviction_score_deterministic >= CONVICTION_WATCH_THRESHOLD
    is_strong = conviction_score_deterministic >= CONVICTION_STRONG_THRESHOLD
    if is_strong:
        triggers.append(f"conviction_strong_{conviction_score_deterministic}")
    elif is_watch:
        weak_triggers.append(f"conviction_watch_{conviction_score_deterministic}")

    # ----- Trigger 3: ML directional edge -----
    if ml_probability is not None:
        if ml_probability >= ML_BULL_THRESHOLD:
            triggers.append(f"ml_bull_{ml_probability:.2f}")
        elif ml_probability <= ML_BEAR_THRESHOLD:
            triggers.append(f"ml_bear_{ml_probability:.2f}")

    # ----- Trigger 4: Regime just changed (within window) -----
    if prev is not None:
        if prev.regime is not None and prev.regime != regime:
            triggers.append(f"regime_change_{prev.regime}_to_{regime}")
        elif prev.ticks_since_regime_change <= REGIME_CHANGE_WINDOW_TICKS:
            triggers.append(f"regime_fresh_{prev.ticks_since_regime_change}")

    # ----- Trigger 5: Structural event fired this tick -----
    # Trendline breakouts were downgraded from strong to weak after an offline
    # hit-rate study: a fresh breakout on its own is not worth an LLM call, but it
    # can corroborate other weak triggers.
    tl_breakout = snapshot.get("tl_breakout")
    if tl_breakout is not None:
        # Only trigger on fresh breakouts, not ongoing
        if prev is None or prev.tl_breakout != tl_breakout:
            weak_triggers.append(f"tl_breakout_{tl_breakout}")

    squeeze_state = snapshot.get("squeeze_state")
    if squeeze_state == "fired":
        if prev is None or prev.squeeze_state != "fired":
            triggers.append("squeeze_fired")

    # Pullback signals are tactically informative but noisy; they transition
    # frequently without material change. Treat as a weak trigger: only worth
    # the LLM's attention when combined with elevated conviction.
    pullback_signal = snapshot.get("pullback_signal")
    if pullback_signal is not None:
        if prev is None or prev.pullback_signal != pullback_signal:
            weak_triggers.append(f"pullback_{pullback_signal}")

    # ----- Trigger 6: Session trend just confirmed -----
    # Weak trigger: session-level moves are significant but not urgent. The
    # LLM should see them when conviction or structural signals corroborate.
    if session_trend_direction != "none":
        if prev is None or prev.session_trend_direction != session_trend_direction:
            weak_triggers.append(f"session_trend_{session_trend_direction}")

    # ----- Trigger 7: Thesis health change -----
    if thesis_state is not None and thesis_state != "intact":
        if prev is None or prev.thesis_state != thesis_state:
            triggers.append(f"thesis_{thesis_state}")

    # Weak triggers need corroboration to justify an LLM call:
    #  - any weak trigger plus a strong trigger invokes (weak adds context)
    #  - two or more weak triggers together invoke (corroboration)
    # A single weak trigger alone is ignored (routine HOLD).
    if weak_triggers and (triggers or len(weak_triggers) >= 2):
        triggers.extend(weak_triggers)

    if triggers:
        return GateDecision(
            invoke=True,
            reason=f"invoke: {', '.join(triggers)}",
            triggers=tuple(triggers),
        )

    return GateDecision(
        invoke=False,
        reason=(
            f"skip: conv={conviction_score_deterministic}"
            + (f" ml={ml_probability:.2f}" if ml_probability is not None else "")
            + f" regime={regime}"
        ),
        triggers=(),
    )


def build_next_context(
    current_regime: str,
    snapshot: dict[str, Any],
    session_trend_direction: str,
    thesis_state: str | None,
    prev: PrevTickContext | None,
) -> PrevTickContext:
    """Build the PrevTickContext for the next tick from current tick state.

    Callers should call this at the end of each tick and hold the result
    to pass into the next invocation of should_invoke_agent().
    """
    if prev is None:
        ticks_since = 999
    elif prev.regime is not None and prev.regime != current_regime:
        ticks_since = 0  # regime changed this tick
    else:
        ticks_since = min(999, prev.ticks_since_regime_change + 1)

    return PrevTickContext(
        regime=current_regime,
        tl_breakout=snapshot.get("tl_breakout"),
        squeeze_state=snapshot.get("squeeze_state"),
        pullback_signal=snapshot.get("pullback_signal"),
        session_trend_direction=session_trend_direction,
        thesis_state=thesis_state,
        ticks_since_regime_change=ticks_since,
    )
