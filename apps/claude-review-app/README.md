# Claude Review App

Read-only browser view of one trading session: candles, indicators, scenarios, the two-agent entry decisions and the fills.

## What it shows

- 3-minute QQQ candles for the session, with EMA 9/21 and session VWAP overlays.
- Sub-charts for RSI 14, StochRSI 14/14/3/3, MACD 12/26/9, volume and RVOL 10, computed from the bars with pandas-ta.
- Key levels read from the tick log: prior-day high, low and close, overnight high and low, daily camarilla levels and the opening range.
- Scenario lifecycles (created, triggered, entry decisions, expiry or invalidation) as zones on the chart, with a side drawer per scenario.
- Each entry-timing call with both agent legs ("opus" and "astra"): decision, reasoning, case for, case against, verdict and raw response. Calls without a trace entry are marked as reconstructed from the scenarios log or as having no model call.
- Round-trip trades rebuilt from the order fills, with entry and exit markers.

## Run it on the synthetic sample

Requires Python 3.12 or 3.13 and [uv](https://docs.astral.sh/uv/). From this directory:

```bash
uv sync
uv run python run_review_app.py
```

Open http://127.0.0.1:8765. The defaults point at `../sample-session/logs/claude` and `../sample-session/market/QQQ_1m.jsonl`, so the sample day 2026-01-07 is listed without further options.

Options:

```bash
uv run python run_review_app.py --port 8765 --log-dir /path/to/logs/claude --bars-file /path/to/QQQ_1m.jsonl
```

Tests:

```bash
uv run pytest -q
```

### Alpaca bars (optional)

When the bars file has no rows for the requested session, the app can fetch 1-minute bars from Alpaca. Install the extra and set the credentials in the environment:

```bash
uv sync --extra alpaca
export ALPACA_API_KEY=...
export ALPACA_API_SECRET=...
```

The fetch uses the SIP feed with split adjustment. Whether the account can read that feed depends on its market-data plan. Completed days are cached in `.cache/`, keyed by the bars file (path, size and modification time) and whether Alpaca credentials are set; a cache entry from another source is fetched again. Reload refetches the bars for any day.

## Data format

The app reads these files under `--log-dir` for a session date `D`. Rows whose timestamp is not dated `D` in US/Eastern time are dropped.

| File | Fields read |
|---|---|
| `ticks/ticks_D.jsonl` | `timestamp`, `price`, and the level fields `prev_day_high`, `prev_day_low`, `prev_day_close`, `overnight_high`, `overnight_low`, `d_h4`, `d_h3`, `d_pivot`, `d_l3`, `d_l4`, `opening_range_high`, `opening_range_low` |
| `scenarios/scenarios_D.jsonl` | `event_timestamp`, `label`, `status` (`created`, `triggered`, `entry_timing`, `expired`, `invalidated`), `source`, and on `created` rows `direction`, `setup_type`, `confidence`, `ttl_minutes`, `trigger_zone`, `target_price`, `trigger_conditions`, `invalidation_conditions`; `entry_timing` rows add `decision`, `reasoning`, `bull_case`, `bear_case`, `verdict` |
| `orders/orders_D.jsonl` | `timestamp`, `action` (`fill` and `partial_fill` are used), `client_order_id`, `symbol`, `side`, `qty_filled` (cumulative), `avg_fill_price`, `reason`, `metadata` (`direction`, `scenario_label`, `spot_price`) |
| `traces/trace_D.md` | Markdown entries headed `### Tick #N \| entry_timing:opus \| HH:MM:SS \| Nms`, each with a `**Model**:` line, a "Human message" block containing `Label: ...`, and a fenced `**Response**:` block holding the agent's JSON |

The bars file is JSONL with one 1-minute bar per line: `{"t": ISO-8601 with offset, "o", "h", "l", "c", "v"}`. The app keeps the regular-hours bars of the last three sessions up to `D` for indicator warm-up.

`../sample-session/generate.py` writes every one of these files from a seeded random walk. `tests/fixtures/sample_day.json` is the `/api/day/2026-01-07` document built from that sample; `UPDATE_FIXTURE=1 uv run pytest tests/test_claude_review_sample_session.py` rewrites it.

## API

- `GET /api/days`: up to six session dates with a ticks file, newest first.
- `GET /api/day/YYYY-MM-DD[?refresh=1]`: the day document (bars, indicators, key levels, scenarios, evaluations, trades, warnings).

## Limitations

- One symbol (QQQ) and one log directory per process. The server binds to 127.0.0.1 only.
- Indicators are recomputed from the bars with standard lengths. They are not the values the trading agent logged at decision time.
- Fill times are the trader's fill-detection times, not broker execution times.
- Chart times are US/Eastern wall-clock times encoded as UTC seconds, so the time axis reads in New York time.
- The upper Python bound comes from pandas-ta 0.4.71b0, which pins numba 0.61.2.

## Authorship

The original private repository refers to this app as Claude's comparison app to the Codex Review App. Inference: it was written by a Claude coding agent.

## Third-party code

`static/vendor/lightweight-charts.standalone.production.js` is TradingView Lightweight Charts v5.2.1, Copyright (c) 2026 TradingView, Inc., licensed under the Apache License 2.0. The license text is in `static/vendor/LICENSE-lightweight-charts.txt` and the upstream NOTICE file is in `static/vendor/NOTICE-lightweight-charts.txt`. As the upstream README requires, the page footer shows the NOTICE attribution and a link to https://www.tradingview.com/, and the chart's `attributionLogo` option is enabled.

## License

Apache-2.0. Copyright Mitchell Foutz.
