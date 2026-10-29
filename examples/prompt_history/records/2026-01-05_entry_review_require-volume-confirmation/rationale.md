# Rationale: entry_review require volume confirmation

This record is a fictional example of the convention.

## Trigger

End-of-day review of 2026-01-02: two approved entries were taken on bars with falling
volume and both reached the stop.

## What the new text enforces

An entry needs participation: the last 5 bars must average at least the 20-bar volume.

## Expected behavior change

Fewer approvals on low-volume drifts. In the trace logs, the share of WAIT decisions whose
reason names the volume ratio should be above zero from the next session on.

## Falsifier

Over the next 10 sessions, approvals blocked by the volume rule hit their target at least as
often as approvals the rule allowed. The rule then removes winners as often as losers and
should be reverted.

## Cross-references

examples/prompt_history/CHANGELOG.md, entry of 2026-01-05.
