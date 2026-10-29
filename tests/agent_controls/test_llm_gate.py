"""Tests for the LLM pre-filter gate."""

from agent_controls.llm_gate import (
    CONVICTION_WATCH_THRESHOLD,
    ML_BEAR_THRESHOLD,
    ML_BULL_THRESHOLD,
    GateDecision,
    PrevTickContext,
    build_next_context,
    is_emergency_trigger,
    is_high_conviction_entry,
    should_invoke_agent,
)


def _empty_snapshot() -> dict:
    return {
        "tl_breakout": None,
        "squeeze_state": "no_squeeze",
        "pullback_signal": None,
    }


def _stable_prev() -> PrevTickContext:
    """A PrevTickContext that implies 'nothing has changed lately'."""
    return PrevTickContext(
        regime="neutral",
        tl_breakout=None,
        squeeze_state="no_squeeze",
        pullback_signal=None,
        session_trend_direction="none",
        thesis_state="intact",
        ticks_since_regime_change=50,
    )


# ---------------------------------------------------------------------------
# Skip cases
# ---------------------------------------------------------------------------


def test_routine_hold_skips_llm():
    """Low conviction, no ML edge, stable regime, no events: skip."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=35,
        ml_probability=0.51,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=_stable_prev(),
    )
    assert d.invoke is False
    assert d.reason.startswith("skip:")
    assert d.triggers == ()


def test_skip_with_missing_ml_signal():
    """When ml_probability is None, the ML triggers should not fire."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=40,
        ml_probability=None,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="bull_trend", ticks_since_regime_change=50),
    )
    assert d.invoke is False


def test_ml_within_neutral_band_does_not_trigger():
    """ML probability near 0.5 should not flag as an edge."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=30,
        ml_probability=0.54,  # below 0.58 bull threshold
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=_stable_prev(),
    )
    assert d.invoke is False


# ---------------------------------------------------------------------------
# Trigger 1: Open position
# ---------------------------------------------------------------------------


def test_open_position_always_invokes():
    """Any open position forces LLM invocation for exit monitoring."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=20,
        ml_probability=0.50,
        regime="neutral",
        positions=[{"symbol": "QQQ250410C00480000"}],
        session_trend_direction="none",
        thesis_state="intact",
        prev=_stable_prev(),
    )
    assert d.invoke is True
    assert "position_open" in d.triggers


# ---------------------------------------------------------------------------
# Trigger 2: High conviction
# ---------------------------------------------------------------------------


def test_conviction_strong_invokes_alone():
    """Strong conviction (>=80) invokes without needing corroboration."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=80,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="bull_trend", ticks_since_regime_change=50),
    )
    assert d.invoke is True
    assert any(t.startswith("conviction_strong") for t in d.triggers)


def test_conviction_watch_alone_skips():
    """Watch-level conviction (70-79) alone should NOT invoke: needs corroboration."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=75,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="bull_trend", ticks_since_regime_change=50),
    )
    assert d.invoke is False


def test_conviction_watch_with_regime_change_invokes():
    """Watch conviction + a corroborating signal (regime change) should invoke."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=75,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="neutral", ticks_since_regime_change=1),
    )
    assert d.invoke is True
    assert any(t.startswith("conviction_watch") for t in d.triggers)
    assert any("regime_change" in t for t in d.triggers)


def test_conviction_below_threshold_skips():
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=CONVICTION_WATCH_THRESHOLD - 1,
        ml_probability=0.50,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=_stable_prev(),
    )
    assert d.invoke is False


# ---------------------------------------------------------------------------
# Trigger 3: ML edge
# ---------------------------------------------------------------------------


def test_ml_bull_edge_invokes():
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=20,
        ml_probability=ML_BULL_THRESHOLD,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="bull_trend", ticks_since_regime_change=50),
    )
    assert d.invoke is True
    assert any(t.startswith("ml_bull") for t in d.triggers)


def test_ml_bear_edge_invokes():
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=20,
        ml_probability=ML_BEAR_THRESHOLD,
        regime="bear_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="bear_trend", ticks_since_regime_change=50),
    )
    assert d.invoke is True
    assert any(t.startswith("ml_bear") for t in d.triggers)


# ---------------------------------------------------------------------------
# Trigger 4: Regime change
# ---------------------------------------------------------------------------


def test_regime_change_invokes():
    """Changed regime this tick should trigger."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="neutral", ticks_since_regime_change=1),
    )
    assert d.invoke is True
    assert any("regime_change" in t for t in d.triggers)


def test_regime_fresh_window_does_not_invoke_alone():
    """Ticks after a regime transition (window=0) should NOT auto-invoke.

    Only the transition tick itself fires via the != check; subsequent ticks
    need another signal to justify an LLM call.
    """
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="bull_trend", ticks_since_regime_change=1),
    )
    assert d.invoke is False


# ---------------------------------------------------------------------------
# Trigger 5: Structural events
# ---------------------------------------------------------------------------


def test_fresh_tl_breakout_alone_does_not_invoke():
    """tl_breakout is a WEAK trigger: a fresh breakout with nothing
    else corroborating should NOT wake the LLM.
    """
    snap = _empty_snapshot()
    snap["tl_breakout"] = "bullish"
    d = should_invoke_agent(
        snapshot=snap,
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=_stable_prev(),
    )
    assert d.invoke is False


def test_fresh_tl_breakout_invokes_when_corroborated_by_watch_conviction():
    """tl_breakout is weak, but combined with a conviction_watch score
    (70-79) it becomes two weak triggers, which IS enough to invoke."""
    snap = _empty_snapshot()
    snap["tl_breakout"] = "bullish"
    d = should_invoke_agent(
        snapshot=snap,
        conviction_score_deterministic=72,  # weak trigger: conviction_watch
        ml_probability=0.50,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=_stable_prev(),
    )
    assert d.invoke is True
    assert any("tl_breakout" in t for t in d.triggers)


def test_ongoing_tl_breakout_does_not_retrigger():
    """Same breakout as previous tick should NOT retrigger."""
    snap = _empty_snapshot()
    snap["tl_breakout"] = "bullish"
    prev = PrevTickContext(
        regime="neutral",
        tl_breakout="bullish",  # same as current
        squeeze_state="no_squeeze",
        pullback_signal=None,
        session_trend_direction="none",
        thesis_state="intact",
        ticks_since_regime_change=50,
    )
    d = should_invoke_agent(
        snapshot=snap,
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=prev,
    )
    assert d.invoke is False


def test_squeeze_fired_invokes():
    snap = _empty_snapshot()
    snap["squeeze_state"] = "fired"
    d = should_invoke_agent(
        snapshot=snap,
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=_stable_prev(),
    )
    assert d.invoke is True
    assert "squeeze_fired" in d.triggers


def test_pullback_signal_alone_skips():
    """Pullback is a weak trigger: alone it should NOT invoke."""
    snap = _empty_snapshot()
    snap["pullback_signal"] = "bullish"
    d = should_invoke_agent(
        snapshot=snap,
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="bull_trend", ticks_since_regime_change=50),
    )
    assert d.invoke is False


def test_pullback_with_watch_conviction_invokes():
    """Pullback + watch-level conviction (70+) should invoke."""
    snap = _empty_snapshot()
    snap["pullback_signal"] = "bullish"
    d = should_invoke_agent(
        snapshot=snap,
        conviction_score_deterministic=72,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=PrevTickContext(regime="bull_trend", ticks_since_regime_change=50),
    )
    assert d.invoke is True
    assert any("pullback" in t for t in d.triggers)
    assert any("conviction_watch" in t for t in d.triggers)


# ---------------------------------------------------------------------------
# Trigger 6: Session trend
# ---------------------------------------------------------------------------


def test_session_trend_alone_skips():
    """Session trend alone is a weak trigger: should NOT invoke by itself."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="bull",
        thesis_state="intact",
        prev=PrevTickContext(
            regime="bull_trend",
            session_trend_direction="none",
            ticks_since_regime_change=50,
        ),
    )
    assert d.invoke is False


def test_session_trend_with_watch_conviction_invokes():
    """Session trend + watch-level conviction should invoke."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=72,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="bull",
        thesis_state="intact",
        prev=PrevTickContext(
            regime="bull_trend",
            session_trend_direction="none",
            ticks_since_regime_change=50,
        ),
    )
    assert d.invoke is True
    assert any("session_trend" in t for t in d.triggers)
    assert any("conviction_watch" in t for t in d.triggers)


def test_ongoing_session_trend_does_not_retrigger():
    """Same session trend as previous tick should not retrigger."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="bull",
        thesis_state="intact",
        prev=PrevTickContext(
            regime="bull_trend",
            session_trend_direction="bull",
            ticks_since_regime_change=50,
        ),
    )
    assert d.invoke is False


# ---------------------------------------------------------------------------
# Trigger 7: Thesis health
# ---------------------------------------------------------------------------


def test_thesis_weakened_transition_invokes():
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="weakened",
        prev=PrevTickContext(
            regime="neutral",
            thesis_state="intact",
            ticks_since_regime_change=50,
        ),
    )
    assert d.invoke is True
    assert any("thesis" in t for t in d.triggers)


def test_thesis_intact_does_not_trigger():
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=_stable_prev(),
    )
    assert d.invoke is False


# ---------------------------------------------------------------------------
# First-tick behavior (prev=None)
# ---------------------------------------------------------------------------


def test_first_tick_with_no_prev_and_routine_state_skips():
    """No prior context, routine state: still skip."""
    d = should_invoke_agent(
        snapshot=_empty_snapshot(),
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="neutral",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=None,
    )
    assert d.invoke is False


def test_first_tick_with_existing_breakout_does_not_invoke_alone():
    """On the very first tick an existing breakout is still just a weak
    trigger and does not invoke alone. With no other signal present it
    should skip."""
    snap = _empty_snapshot()
    snap["tl_breakout"] = "bullish"
    d = should_invoke_agent(
        snapshot=snap,
        conviction_score_deterministic=30,
        ml_probability=0.50,
        regime="bull_trend",
        positions=[],
        session_trend_direction="none",
        thesis_state="intact",
        prev=None,
    )
    assert d.invoke is False


# ---------------------------------------------------------------------------
# build_next_context
# ---------------------------------------------------------------------------


def test_build_next_context_first_tick():
    """No prev: ticks_since starts at 999 and regime is captured."""
    ctx = build_next_context(
        current_regime="bull_trend",
        snapshot=_empty_snapshot(),
        session_trend_direction="none",
        thesis_state="intact",
        prev=None,
    )
    assert ctx.regime == "bull_trend"
    assert ctx.ticks_since_regime_change == 999


def test_build_next_context_regime_change_resets_counter():
    prev = PrevTickContext(regime="neutral", ticks_since_regime_change=20)
    ctx = build_next_context(
        current_regime="bull_trend",  # changed
        snapshot=_empty_snapshot(),
        session_trend_direction="none",
        thesis_state="intact",
        prev=prev,
    )
    assert ctx.regime == "bull_trend"
    assert ctx.ticks_since_regime_change == 0


def test_build_next_context_regime_stable_increments_counter():
    prev = PrevTickContext(regime="bull_trend", ticks_since_regime_change=5)
    ctx = build_next_context(
        current_regime="bull_trend",
        snapshot=_empty_snapshot(),
        session_trend_direction="none",
        thesis_state="intact",
        prev=prev,
    )
    assert ctx.ticks_since_regime_change == 6


# ---------------------------------------------------------------------------
# GateDecision cadence_suppressed field
# ---------------------------------------------------------------------------


def test_gate_decision_cadence_suppressed_default():
    """cadence_suppressed defaults to False for backward compat."""
    gd = GateDecision(invoke=True, reason="test")
    assert gd.cadence_suppressed is False


def test_gate_decision_cadence_suppressed_explicit():
    """cadence_suppressed can be set explicitly."""
    gd = GateDecision(invoke=False, reason="cadence", cadence_suppressed=True)
    assert gd.cadence_suppressed is True


# ---------------------------------------------------------------------------
# is_emergency_trigger: bypasses cadence suppression on structural events
# ---------------------------------------------------------------------------


def _gate(triggers: tuple[str, ...]) -> GateDecision:
    return GateDecision(invoke=True, reason="test", triggers=triggers)


def test_emergency_thesis_weakened_exact_match():
    assert is_emergency_trigger(_gate(("thesis_weakened",))) is True


def test_emergency_thesis_invalidated_exact_match():
    assert is_emergency_trigger(_gate(("thesis_invalidated",))) is True


def test_emergency_regime_change_prefix_match():
    """regime_change triggers carry a transition detail suffix."""
    assert is_emergency_trigger(_gate(("regime_change_bull_trend_to_strong_bull_trend",))) is True


def test_emergency_regime_change_bare_still_matches():
    """If ever emitted as a bare prefix, must still match."""
    assert is_emergency_trigger(_gate(("regime_change_",))) is True


def test_emergency_no_substring_collision_on_thesis():
    """'thesis_intact' must NOT trigger emergency (was a bug in the old
    substring match: 'thesis_' substring would collide with any thesis state)."""
    assert is_emergency_trigger(_gate(("thesis_intact",))) is False


def test_emergency_no_substring_collision_on_regime():
    """'regime_fresh_3' must NOT trigger emergency (the old substring match
    against 'regime_change' would not have collided here; regression proof)."""
    assert is_emergency_trigger(_gate(("regime_fresh_3",))) is False


def test_emergency_regime_changed_not_matched():
    """'regime_changed_later' must NOT match 'regime_change_' because the
    prefix requires an underscore after 'change', not 'changed'."""
    assert is_emergency_trigger(_gate(("regime_changed_later",))) is False


def test_emergency_thesis_weakened_override_not_matched():
    """A hypothetical future 'thesis_weakened_override' must NOT match
    the exact tag 'thesis_weakened' (no substring collision)."""
    assert is_emergency_trigger(_gate(("thesis_weakened_override",))) is False


def test_emergency_empty_triggers():
    assert is_emergency_trigger(_gate(())) is False


def test_emergency_non_emergency_triggers_only():
    assert (
        is_emergency_trigger(_gate(("position_open", "conviction_watch_72", "squeeze_fired")))
        is False
    )


def test_emergency_mixed_triggers_with_one_emergency():
    assert (
        is_emergency_trigger(_gate(("position_open", "thesis_invalidated", "squeeze_fired")))
        is True
    )


# ---------------------------------------------------------------------------
# is_high_conviction_entry: bypasses cadence for strong entry signals
# when flat
# ---------------------------------------------------------------------------


def test_high_conviction_entry_when_flat():
    """conviction_strong_85 should bypass cadence when no position is open."""
    assert is_high_conviction_entry(_gate(("conviction_strong_85",)), has_position=False) is True


def test_high_conviction_entry_when_positioned():
    """conviction_strong_85 must NOT bypass cadence when holding a position:
    cadence prevents repeated EXIT decisions on consecutive ticks."""
    assert is_high_conviction_entry(_gate(("conviction_strong_85",)), has_position=True) is False


def test_high_conviction_entry_watch_not_strong():
    """conviction_watch_75 is not strong enough to bypass cadence."""
    assert is_high_conviction_entry(_gate(("conviction_watch_75",)), has_position=False) is False


def test_high_conviction_entry_mixed_triggers():
    """conviction_strong among other triggers still bypasses when flat."""
    assert (
        is_high_conviction_entry(
            _gate(("squeeze_fired", "conviction_strong_92")), has_position=False
        )
        is True
    )


def test_high_conviction_entry_no_conviction_trigger():
    """Non-conviction triggers do not bypass cadence via this path."""
    assert (
        is_high_conviction_entry(_gate(("position_open", "squeeze_fired")), has_position=False)
        is False
    )


def test_high_conviction_entry_empty_triggers():
    assert is_high_conviction_entry(_gate(()), has_position=False) is False
