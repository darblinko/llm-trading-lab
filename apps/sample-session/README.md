# Sample session

One synthetic trading session (2026-01-07, symbol QQQ) in the log layout that both review apps read. Prices are a seeded random walk starting at 100.00. Scenario levels, fills and exits are derived from that walk. Agent responses are fixed placeholder strings. No file here comes from a recorded session.

Regenerate (Python 3.12 or later, standard library only; output is byte-identical between runs):

```bash
python3 generate.py
```

Check that the committed files match the generator: `uv run pytest -q`.

| Path | Contents |
|---|---|
| `logs/claude/ticks/ticks_2026-01-07.jsonl` | 130 ticks, 3 minutes apart, with price, indicator observations and key levels |
| `logs/claude/scenarios/scenarios_2026-01-07.jsonl` | 3 scenarios: an initial-thesis breakout call (invalidated after entry), a refresh put fade (split vote, a pre-check pass, expiry) and a refresh reclaim call (partial entry fill, exit on its TTL) |
| `logs/claude/orders/orders_2026-01-07.jsonl` | submit, partial fill and fill rows for 2 round trips |
| `logs/claude/traces/trace_2026-01-07.md` | thesis calls, 3 two-agent entry-timing calls and 2 exit-fill events |
| `logs/claude/daily_thesis/thesis_2026-01-07.md` | placeholder thesis |
| `logs/shared/snapshot.json` | 130 three-minute bars for the session day (read by the Codex app) |
| `market/QQQ_1m.jsonl` | regular-hours 1-minute bars for 2026-01-05 to 2026-01-07 (read by the Claude app) |
