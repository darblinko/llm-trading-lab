"""Read-only Alpaca data requests and isolated, atomic candle archives."""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

from review_app.records import ET, Row, number, read_json, timestamp

logger = logging.getLogger(__name__)


def atomic_json(path: Path, data: Row) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=path.parent, delete=False) as file:
        temporary = Path(file.name)
        try:
            json.dump(data, file, allow_nan=False)
            file.flush()
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


ALPACA_URLS = {
    "calendar": "https://paper-api.alpaca.markets/v2/calendar",
    "bars": "https://data.alpaca.markets/v2/stocks/QQQ/bars",
}


def credentials(kind: str) -> tuple[str, str, str] | None:
    """Return (key, secret, url) from ALPACA_API_KEY and ALPACA_API_SECRET, or None."""
    key, secret = os.getenv("ALPACA_API_KEY"), os.getenv("ALPACA_API_SECRET")
    if key and secret and kind in ALPACA_URLS:
        return key, secret, ALPACA_URLS[kind]
    return None


def alpaca_get(kind: str, params: Row) -> object:
    auth = credentials(kind)
    if not auth:
        raise ValueError("Alpaca credentials are unavailable to the review process.")
    key, secret, url = auth
    headers = {"APCA-API-KEY-ID": key, "APCA-API-SECRET-KEY": secret}
    with httpx.Client(timeout=20, headers=headers) as client:
        response = client.get(url, params=params)
        response.raise_for_status()
        return response.json()


def sync_calendar(cache_dir: Path, as_of: date) -> None:
    start, end = as_of - timedelta(days=40), as_of + timedelta(days=7)
    data = alpaca_get("calendar", {"start": start.isoformat(), "end": end.isoformat()})
    if not isinstance(data, list):
        raise ValueError("Alpaca returned an invalid calendar.")
    rows = [{"date": row["date"], "open": row["open"], "close": row["close"]} for row in data]
    atomic_json(
        cache_dir / "calendar.json",
        {
            "start": start.isoformat(),
            "end": end.isoformat(),
            "sessions": rows,
            "source": "Alpaca",
        },
    )


def normalize_candles(records: list[Row], window: Row) -> list[Row]:
    by_time: dict[int, Row] = {}
    for record in records:
        ts = (
            record.get("time")
            if isinstance(record.get("time"), int)
            else timestamp(record.get("ts", record.get("t")))
        )
        values = {
            key: number(record.get(key, record.get(short)))
            for key, short in (("open", "o"), ("high", "h"), ("low", "l"), ("close", "c"))
        }
        if ts is None or not window["open"] <= ts < window["close"] or None in values.values():
            continue
        if values["low"] > min(values["open"], values["close"]) or values["high"] < max(
            values["open"], values["close"]
        ):
            continue
        by_time[ts] = {
            "time": ts,
            **values,
            "volume": number(record.get("volume", record.get("v"))) or 0,
        }
    return [by_time[ts] for ts in sorted(by_time)]


def resample_minutes(records: list[Row], window: Row) -> list[Row]:
    buckets: dict[int, Row] = {}
    for bar in normalize_candles(records, window):
        ts = bar["time"] - bar["time"] % 180
        if ts not in buckets:
            buckets[ts] = {**bar, "time": ts}
        else:
            current = buckets[ts]
            current.update(
                high=max(current["high"], bar["high"]),
                low=min(current["low"], bar["low"]),
                close=bar["close"],
                volume=current["volume"] + bar["volume"],
            )
    return list(buckets.values())


def backfill_candles(cache_dir: Path, window: Row) -> int:
    now = int(datetime.now(UTC).timestamp())
    end = min(window["close"], now - now % 180)
    if end <= window["open"]:
        return 0
    params: Row = {
        "start": datetime.fromtimestamp(window["open"], UTC).isoformat(),
        "end": datetime.fromtimestamp(end - 1, UTC).isoformat(),
        "timeframe": "1Min",
        "feed": "sip",
        "adjustment": "split",
        "limit": 10000,
    }
    rows: list[Row] = []
    while True:
        response = alpaca_get("bars", params)
        if not isinstance(response, dict):
            raise ValueError("Alpaca returned invalid bars.")
        rows.extend(response.get("bars") or [])
        token = response.get("next_page_token")
        if not token:
            break
        params["page_token"] = token
    bars = resample_minutes(rows, window)
    if not bars:
        raise ValueError(f"Alpaca returned no QQQ SIP bars for {window['date']}.")
    save_candles(cache_dir, window["date"], bars, "Alpaca SIP · 1m aggregated to 3m")
    return len(bars)


def save_candles(cache_dir: Path, day: str, bars: list[Row], origin: str) -> None:
    path = cache_dir / "candles" / f"QQQ_{day}.json"
    existing = read_json(path, [])
    merged = {bar["time"]: bar for bar in existing.get("bars", [])}
    merged.update({bar["time"]: bar for bar in bars})
    origins = sorted(set(existing.get("origins", []) + [origin]))
    atomic_json(
        path,
        {
            "date": day,
            "symbol": "QQQ",
            "interval": "3m",
            "origins": origins,
            "bars": [merged[ts] for ts in sorted(merged)],
            "updated_at": datetime.now(ET).isoformat(),
        },
    )


def archive_snapshot(root: Path, cache_dir: Path) -> None:
    envelope = read_json(root / "shared/snapshot.json", [])
    produced = timestamp(envelope.get("produced_at_et"))
    if produced is None:
        return
    day = datetime.fromtimestamp(produced, ET).date().isoformat()
    from review_app.calendar import session_window

    window = session_window(cache_dir, day)
    bars = normalize_candles(envelope.get("today_bars") or [], window)
    completed = [bar for bar in bars if bar["time"] + 180 <= produced]
    if completed:
        save_candles(cache_dir, day, completed, "Shared producer snapshot")


def load_candles(cache_dir: Path, window: Row, warnings: list[str]) -> tuple[list[Row], str]:
    path = cache_dir / "candles" / f"QQQ_{window['date']}.json"
    data = read_json(path, warnings)
    bars = normalize_candles(data.get("bars", []), window)
    origin = "; ".join(data.get("origins", [])) if bars else "Recorded tick prices"
    if not bars:
        warnings.append(
            "Candles unavailable for this day. Showing recorded price observations; "
            "ticks do not contain OHLC."
        )
    return bars, origin
