"""Tests for claude_review.leg_reconstruction."""

from claude_review.leg_reconstruction import reconstruct_legs, split_by_agent, split_headline


def test_split_headline_returns_ballot_and_body() -> None:
    ballot, body = split_headline(
        "Unanimous enter (opus=enter_now, astra=enter_now). opus: a | astra: b"
    )

    assert ballot == {"opus": "enter_now", "astra": "enter_now"}
    assert body == "opus: a | astra: b"


def test_split_headline_leaves_other_text_alone() -> None:
    text = "Pre-check: pass before any model call (filter not met)"

    assert split_headline(text) == ({}, text)


def test_split_by_agent_keeps_pipes_inside_text() -> None:
    assert split_by_agent("opus: level | average lost | astra: volume light") == {
        "opus": "level | average lost",
        "astra": "volume light",
    }


def test_split_by_agent_without_prefix_is_empty() -> None:
    assert split_by_agent("Consensus call failed: timeout") == {}


def test_override_row_takes_decisions_from_the_verdict_ballot() -> None:
    legs = reconstruct_legs(
        reasoning="Post-check override: synthetic reason",
        bull_case="opus: for | astra: also for",
        bear_case="",
        verdict="Unanimous enter (opus=enter_now, astra=enter_now). opus: go | astra: go now",
    )

    assert legs["opus"]["decision"] == "enter_now"
    assert (legs["astra"]["case_for"], legs["astra"]["verdict"]) == ("also for", "go now")
    assert legs["astra"]["reasoning"] == ""


def test_agent_with_no_text_or_ballot_is_none() -> None:
    legs = reconstruct_legs(reasoning="", bull_case="astra: only astra", bear_case="", verdict="")

    assert legs["opus"] is None
    assert legs["astra"]["case_for"] == "only astra"
    assert legs["astra"]["decision"] == ""
