"""Rebuild per-agent legs from the combined text of a scenarios-log entry_timing row.

The trading agent's consensus step joins each field as 'opus: ... | astra: ...'
and prefixes reasoning and verdict with a headline such as
'No consensus (opus=wait, astra=pass). '. Reversing that format recovers each
agent's decision and text when the trace has no entry for the call.
"""

from __future__ import annotations

import re

from claude_review.payload_types import AgentLeg

LEG_NAMES = ("opus", "astra")
HEADLINE_PATTERN = re.compile(
    r"^(?:Unanimous enter|Unanimous pass|No consensus) \((?P<ballot>[^)]*)\)\.\s*(?P<body>.*)$",
    re.DOTALL,
)
BALLOT_PATTERN = re.compile(r"(\w+)=(\w+)")
AGENT_SPLIT_PATTERN = re.compile(r"(?:^| \| )(" + "|".join(LEG_NAMES) + r"): ")


def reconstruct_legs(
    reasoning: str, bull_case: str, bear_case: str, verdict: str
) -> dict[str, AgentLeg | None]:
    """Return a leg per agent; an agent with no ballot entry and no text gets None."""
    ballot, reasoning_body = split_headline(reasoning)
    verdict_ballot, verdict_body = split_headline(verdict)
    decisions = {**verdict_ballot, **ballot}
    fields = {
        "reasoning": split_by_agent(reasoning_body),
        "case_for": split_by_agent(bull_case),
        "case_against": split_by_agent(bear_case),
        "verdict": split_by_agent(verdict_body),
    }
    return {name: _leg(name, decisions, fields) for name in LEG_NAMES}


def split_headline(text: str) -> tuple[dict[str, str], str]:
    """Separate a consensus headline into its ballot and the per-agent body that follows it."""
    match = HEADLINE_PATTERN.match(text)
    if match is None:
        return {}, text
    return dict(BALLOT_PATTERN.findall(match.group("ballot"))), match.group("body")


def split_by_agent(text: str) -> dict[str, str]:
    """Map each agent name to its text in an 'opus: ... | astra: ...' string."""
    parts = AGENT_SPLIT_PATTERN.split(text)
    return {parts[i]: parts[i + 1].strip() for i in range(1, len(parts) - 1, 2)}


def _leg(
    name: str, decisions: dict[str, str], fields: dict[str, dict[str, str]]
) -> AgentLeg | None:
    texts = {field: by_agent.get(name, "") for field, by_agent in fields.items()}
    if name not in decisions and not any(texts.values()):
        return None
    return AgentLeg(
        model="",
        decision=decisions.get(name, ""),
        reasoning=texts["reasoning"],
        key_factors=[],
        case_for=texts["case_for"],
        case_against=texts["case_against"],
        verdict=texts["verdict"],
        wait_for="",
        latency_ms=None,
        raw_response="",
    )
