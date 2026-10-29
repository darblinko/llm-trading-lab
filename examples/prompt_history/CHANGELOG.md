# Change log (example)

Every change to trading logic or an LLM prompt gets an entry before the system restarts.

## 2026-01-05 08:45 ET: require volume confirmation in entry review

**Files**: `prompts/entry_review.md`
**Trigger**: end-of-day review of 2026-01-02
**Change**: entry review returns WAIT when the 5-bar mean volume is below the 20-bar mean.
**Why**: two approved entries on falling volume both stopped out.
**Contradiction check**: none found
**Validation**: paper trading; fill Outcome after at least one session
**Status**: live since 2026-01-05 09:30 ET
**Prompt history**: examples/prompt_history/records/2026-01-05_entry_review_require-volume-confirmation
