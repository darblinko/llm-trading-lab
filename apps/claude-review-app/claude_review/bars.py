"""QQQ minute bars for one review session: date-range fetch, RTH trim, JSON cache.

Indicator warm-up needs the sessions before the reviewed one, so the kept
window is the last SESSIONS_KEPT regular-hours session dates up to and
including the session date. Bars come from a local JSONL file of 1-min bars
(the synthetic sample by default) and, when that file does not cover the
session, from Alpaca historical data if ALPACA_API_KEY and ALPACA_API_SECRET
are set and alpaca-py is installed. Market data only: no trading client is
built here.
"""

from __future__ import annotations

import json
import logging
import os
from collections.abc import Callable
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import NamedTuple
from zoneinfo import ZoneInfo

import pandas as pd

from claude_review.chart_time import ET_ZONE, to_chart_time
from claude_review.market_helpers import SYMBOL, filter_rth, resample_to_3m
from claude_review.payload_types import Bar

logger = logging.getLogger(__name__)

ET = ZoneInfo(ET_ZONE)
LOOKBACK_DAYS = 7
SESSIONS_KEPT = 3
SESSION_CLOSE = time(16, 0)
BAR_COLUMNS = ["open", "high", "low", "close", "volume"]
FILE_COLUMNS = {"o": "open", "h": "high", "l": "low", "c": "close", "v": "volume"}

MinuteFetch = Callable[[datetime, datetime], pd.DataFrame]


class BarsUnavailable(RuntimeError):
    """The session's bars could not be fetched, or the session has none."""


class SessionBars(NamedTuple):
    """RTH bars for one session (naive ET index, lowercase columns)."""

    day_minute: pd.DataFrame
    bars_3m: pd.DataFrame


def make_fetch(bars_file: Path | None) -> MinuteFetch:
    """Return a MinuteFetch over the local bars file, falling back to Alpaca when configured."""
    alpaca = make_alpaca_fetch()

    def fetch(start: datetime, end: datetime) -> pd.DataFrame:
        if bars_file is not None and bars_file.exists():
            local = read_bars_file(bars_file, start, end)
            if (local.index.normalize() == pd.Timestamp(end.date())).any() or alpaca is None:
                return local
        if alpaca is None:
            raise BarsUnavailable(
                "no local bars file and no Alpaca credentials (ALPACA_API_KEY, ALPACA_API_SECRET)"
            )
        return alpaca(start, end)

    return fetch


def bars_source_id(bars_file: Path | None) -> str:
    """Identify the bar source a cache entry came from.

    A local file is identified by its resolved path, size and modification
    time, so a different or edited file invalidates the cache. Alpaca is
    identified by whether credentials are set; the values are not used.
    """
    parts = []
    if bars_file is not None and bars_file.exists():
        stat = bars_file.stat()
        parts.append(f"file:{bars_file.resolve()}:{stat.st_size}:{stat.st_mtime_ns}")
    else:
        parts.append("file:none")
    alpaca = bool(os.environ.get("ALPACA_API_KEY") and os.environ.get("ALPACA_API_SECRET"))
    parts.append(f"alpaca:{'on' if alpaca else 'off'}")
    return "|".join(parts)


def read_bars_file(path: Path, start: datetime, end: datetime) -> pd.DataFrame:
    """1-min bars from JSONL rows {"t", "o", "h", "l", "c", "v"} with start <= t < end."""
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if not rows:
        return pd.DataFrame(columns=BAR_COLUMNS)
    frame = pd.DataFrame(rows).rename(columns=FILE_COLUMNS)
    index = pd.DatetimeIndex(pd.to_datetime(frame.pop("t"), utc=True)).tz_convert(ET_ZONE)
    frame = frame.set_axis(index.tz_localize(None), axis=0)[BAR_COLUMNS].astype(float)
    lower, upper = _naive_et(start), _naive_et(end)
    return frame[(frame.index >= lower) & (frame.index < upper)]


def _naive_et(stamp: datetime) -> pd.Timestamp:
    value = pd.Timestamp(stamp)
    return value.tz_convert(ET_ZONE).tz_localize(None) if value.tzinfo else value


def make_alpaca_fetch() -> MinuteFetch | None:
    """Return a MinuteFetch over Alpaca SIP minute bars, or None when it is not configured."""
    key, secret = os.environ.get("ALPACA_API_KEY"), os.environ.get("ALPACA_API_SECRET")
    if not key or not secret:
        logger.info("ALPACA_API_KEY or ALPACA_API_SECRET not set; Alpaca bars disabled")
        return None
    try:
        from alpaca.data.enums import Adjustment, DataFeed
        from alpaca.data.historical import StockHistoricalDataClient
        from alpaca.data.requests import StockBarsRequest
        from alpaca.data.timeframe import TimeFrame
    except ImportError:
        logger.warning("alpaca-py is not installed; Alpaca bars disabled")
        return None
    client = StockHistoricalDataClient(key, secret)

    def fetch(start: datetime, end: datetime) -> pd.DataFrame:
        request = StockBarsRequest(
            symbol_or_symbols=[SYMBOL],
            timeframe=TimeFrame.Minute,
            start=start,
            end=end,
            adjustment=Adjustment.SPLIT,
            feed=DataFeed.SIP,
        )
        return _normalize_alpaca_frame(client.get_stock_bars(request).df)

    return fetch


def _normalize_alpaca_frame(raw: pd.DataFrame) -> pd.DataFrame:
    """One symbol, lowercase columns, naive ET index."""
    if raw.empty:
        return raw
    frame = raw.xs(SYMBOL, level=0) if isinstance(raw.index, pd.MultiIndex) else raw
    naive_index = frame.index.tz_convert(ET_ZONE).tz_localize(None)
    return frame.set_axis(naive_index, axis=0).rename(columns=str.lower)


def load_session_bars(
    session_date: date,
    cache_dir: Path,
    fetch: MinuteFetch,
    today: date,
    refresh: bool = False,
    source_id: str = "",
) -> SessionBars:
    """Return the session's RTH 1-min bars and the 3-min bars of the kept sessions.

    Completed days (session_date < today) are cached with source_id; a cache
    entry written from another source is ignored, and refresh skips the read.
    """
    cache_path = cache_dir / f"{SYMBOL}_1m_{session_date.isoformat()}.json"
    minute = None if refresh else _read_cache(cache_path, session_date, source_id)
    if minute is None:
        minute = _fetch_session_window(session_date, fetch)
        if session_date < today:
            _write_cache(cache_path, minute, session_date, source_id)
    day_minute = minute[minute.index.normalize() == pd.Timestamp(session_date)]
    return SessionBars(day_minute=day_minute, bars_3m=resample_to_3m(minute))


def _fetch_session_window(session_date: date, fetch: MinuteFetch) -> pd.DataFrame:
    start = datetime.combine(session_date - timedelta(days=LOOKBACK_DAYS), time(0, 0), ET)
    end = datetime.combine(session_date, SESSION_CLOSE, ET)
    try:
        minute = fetch(start, end)
    except Exception as exc:
        logger.error("Minute bar fetch failed for %s (%s to %s): %s", session_date, start, end, exc)
        raise BarsUnavailable(f"minute bar fetch failed for {session_date}: {exc}") from exc
    return _keep_recent_sessions(minute, session_date)


def _keep_recent_sessions(minute: pd.DataFrame, session_date: date) -> pd.DataFrame:
    """RTH bars of the last SESSIONS_KEPT session dates ending at session_date."""
    if minute.empty or not isinstance(minute.index, pd.DatetimeIndex):
        logger.error("Minute bar fetch for %s returned no bars", session_date)
        raise BarsUnavailable(f"no minute bars returned for {session_date}")
    rth = filter_rth(minute)
    day_index = rth.index.normalize()
    session_days = sorted(set(day_index[day_index <= pd.Timestamp(session_date)]))
    if not session_days or session_days[-1] != pd.Timestamp(session_date):
        logger.error("No regular-hours bars for %s in the fetched window", session_date)
        raise BarsUnavailable(f"no regular-hours bars for {session_date}")
    first_day = session_days[-SESSIONS_KEPT:][0]
    return rth[(day_index >= first_day) & (day_index <= pd.Timestamp(session_date))]


def _read_cache(path: Path, session_date: date, source_id: str) -> pd.DataFrame | None:
    if not path.exists():
        return None
    try:
        document = json.loads(path.read_text())
        if document.get("source", "") != source_id:
            logger.info("Bar cache %s is from another source; refetching", path)
            return None
        index = pd.DatetimeIndex(document["index"])
        if not (index.normalize() == pd.Timestamp(session_date)).any():
            raise ValueError("cache holds no bars for the session day")
        return pd.DataFrame(document["data"], index=index, columns=document["columns"], dtype=float)
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
        logger.warning("Ignoring unreadable bar cache %s for %s: %s", path, session_date, exc)
        return None


def _write_cache(path: Path, minute: pd.DataFrame, session_date: date, source_id: str) -> None:
    document = {
        "symbol": SYMBOL,
        "source": source_id,
        "session_date": session_date.isoformat(),
        "columns": list(minute.columns),
        "index": [stamp.isoformat() for stamp in minute.index],
        "data": minute.to_numpy(dtype=float).tolist(),
    }
    temp_path = path.with_name(path.name + ".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        temp_path.write_text(json.dumps(document))
        os.replace(temp_path, path)
    except OSError as exc:
        logger.warning("Could not write bar cache %s for %s: %s", path, session_date, exc)


def bars_to_payload(bars_3m: pd.DataFrame, session_date: date) -> list[Bar]:
    """The session day's 3-min bars as chart-time candles."""
    day = bars_3m[bars_3m.index.normalize() == pd.Timestamp(session_date)][BAR_COLUMNS]
    return [
        Bar(
            time=to_chart_time(stamp),
            open=float(op),
            high=float(hi),
            low=float(lo),
            close=float(cl),
            volume=float(vol),
        )
        for stamp, (op, hi, lo, cl, vol) in zip(day.index, day.to_numpy(dtype=float), strict=True)
    ]
