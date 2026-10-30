# Codex Review App

Local chart and decision journal for the recorded sessions of one trading agent instance.

## What it shows

- A day picker over the latest session and up to five earlier ones.
- 3-minute QQQ candles when they are available, otherwise a labelled line of recorded tick prices. The app never builds OHLC candles from ticks.
- Indicator observations as logged at tick time: RSI, StochRSI K and D, MACD histogram, RVOL, CVD, VWAP, EMA 9 and EMA 21. The chart shows the last observation in each 3-minute interval; an interval with no observation is drawn as a gap, and values are not carried forward into it. Two observations more than 180 s apart in adjacent intervals are drawn as connected points.
- Scenario revisions with their lifetimes, trigger zones, targets and price invalidations, plus a measured outcome on the candles after the first trigger.
- The two agents' recorded answers for each entry-timing call ("Claude Opus" and "OpenAI Astra" cards), linked to the scenario event they belong to, with a side-by-side expanded view.
- Confirmed fills with cumulative partial fills deduplicated, open positions, and realized profit or loss at weighted average cost before fees.
- The daily thesis Markdown.

## Run it on the synthetic sample

Requires Python 3.12 or later, [uv](https://docs.astral.sh/uv/) and Node 24 (`.nvmrc`; the build rejects other Node majors). From this directory:

```bash
uv sync
cd web
npm ci
npm run build
cd ..
uv run python run.py
```

Open http://127.0.0.1:8766. The default log root is `../sample-session/logs`, which holds the 2026-01-07 sample session. Without Alpaca credentials the app runs offline and archives the candles from `logs/shared/snapshot.json` into `data/candles/`.

Launcher options:

```bash
uv run python run.py --port 8766 --host 127.0.0.1
uv run python run.py --logs /path/to/logs
uv run python run.py --ticks-dir /path/to/logs/claude/ticks
uv run python run.py --as-of 2026-01-07
uv run python run.py --offline
uv run python run.py --sync-only
```

Development: run `uv run python run.py` and, in `web/`, `npm run dev`. Vite serves on 5174 and proxies `/api` to 8766.

Tests:

```bash
uv run pytest -q
cd web
npm ci
npx playwright install --with-deps chromium
npm test
```

`npm ci` does not download a browser; `npx playwright install --with-deps chromium` installs the Chromium build that matches the installed Playwright version, plus its system packages. `npm test` builds the frontend, starts a preview server on 4174 and runs the Playwright checks against isolated fixtures. It also starts the backend on 4175 with `uv run python run.py --offline --as-of 2026-01-07` and runs `tests/backend.spec.ts` against the committed sample session without route mocks, so it needs `uv`. It also starts the static review app in `../claude-review-app` on 4176 for `tests/staticApp.spec.ts`.

### Alpaca data (optional)

Copy `.env.example` into your shell environment or export the variables directly; the app reads only the process environment.

```bash
export ALPACA_API_KEY=...
export ALPACA_API_SECRET=...
```

With credentials the backend fetches the exchange calendar from the Alpaca trading API and backfills QQQ 1-minute SIP bars from the Alpaca data API, aggregated to 3-minute candles. Once a calendar covering the review window is cached, the day picker lists only calendar sessions near today. `--offline` alone does not change that, because it still reads the cached calendar. To reopen the 2026-01-07 sample after a calendar has been cached, run `uv run python run.py --offline --as-of 2026-01-07`. `--as-of` anchors the window to the sample date, and `--offline` keeps the backfill from merging real bars into the sample's candle cache.

## Data format

For an instance (`claude` or `codex`) and session date `D` under the log root:

| File | Fields read |
|---|---|
| `<instance>/ticks/ticks_D.jsonl` | `timestamp`, `price`, `rsi`, `stochrsi_k`, `stochrsi_d`, `macd_hist`, `rvol`, `cvd_21`, `vwap`, `ema_9`, `ema_21` |
| `<instance>/scenarios/scenarios_D.jsonl` | `event_timestamp`, `label`, `status`, `source`, `direction`, `setup_type`, `confidence`, `ttl_minutes`, `trigger_zone`, `target_price`, `trigger_conditions`, `invalidation_conditions`; `entry_timing` rows add `decision` and `reasoning` |
| `<instance>/orders/orders_D.jsonl` | `timestamp`, `action`, `status`, `client_order_id` or `broker_order_id`, `symbol`, `side`, `qty_filled` (cumulative), `avg_fill_price`, optional `filled_at`, `reason`, `metadata` (`direction`, `scenario_label`, `reason`) |
| `<instance>/traces/trace_D.md` | entries headed `### Tick #N \| entry_timing:opus \| HH:MM:SS \| Nms` (or `astra`), with a `**Model**:` line, a "Human message" block containing `Label: ...` and a fenced `**Response**:` JSON block |
| `<instance>/daily_thesis/thesis_D.md` | shown as Markdown |
| `shared/snapshot.json` | `produced_at_et` and `today_bars` (`ts` or `t`, `open`/`o`, `high`/`h`, `low`/`l`, `close`/`c`, `volume`/`v`) |

Timestamps without an offset are read as America/New_York. Generated calendar and candle caches stay in this app's `data/` directory; the log root is never written.

## Limitations

- One symbol (QQQ). Instances are limited to the directory names `claude` and `codex`.
- Without a cached Alpaca calendar, session bounds are an unverified 09:30 to 16:00 ET, and the app says so.
- Tick logs have no OHLC. Days without archived or fetched candles show a price line only.
- Indicator values are the logged observations. They are not recomputed from the candles.
- Fill times are broker execution times only when the order log has `filled_at` or `executed_at`; otherwise they are fill-detection times.
- Vite reports a bundle above 500 kB and the Python tests report a Starlette TestClient deprecation warning. Neither stops the build or the app.

## Authorship

The original private repository's handoff note records that this app was implemented in an OpenAI Codex agent session.

## Third-party code

Charts use [TradingView Lightweight Charts](https://www.tradingview.com/lightweight-charts/) (npm `lightweight-charts`), licensed under the Apache License 2.0. As the upstream README requires, the chart's built-in `attributionLogo` link is enabled and the page footer shows the attribution notice from the upstream NOTICE file ("TradingView Lightweight Charts™, Copyright (c) 2025 TradingView, Inc.") with a link to https://www.tradingview.com/. The npm package does not include the NOTICE file, so the v5.2.1 NOTICE is kept at `web/public/NOTICE-lightweight-charts.txt`, which Vite copies into `web/dist/` next to the bundle.

## License

Apache-2.0. Copyright Mitchell Foutz.
