"""Read and normalize one trading session, cached by source-file revision."""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime
from pathlib import Path

from review_app.calendar import recent_sessions, session_window
from review_app.market import (
    archive_snapshot,
    backfill_candles,
    credentials,
    load_candles,
    sync_calendar,
)
from review_app.reasoning import link_decisions, read_decisions
from review_app.records import ET, Row, number, read_jsonl, read_text, source, timed_rows
from review_app.scenarios import add_outcomes, reconstruct_scenarios
from review_app.trades import read_fills

logger = logging.getLogger(__name__)
INDICATORS = (
    "rsi",
    "stochrsi_k",
    "stochrsi_d",
    "macd_hist",
    "rvol",
    "cvd_21",
    "vwap",
    "ema_9",
    "ema_21",
)


class ReviewStore:
    def __init__(self, root: Path, cache_dir: Path, as_of: date | None = None) -> None:
        self.root = root
        self.cache_dir = cache_dir
        self.as_of = as_of
        self._cache: dict[tuple[str, str], tuple[tuple, Row]] = {}
        self._lock = threading.RLock()
        self.sync_status = "Local logs ready"
        self._calendar_day: date | None = None
        self._backfilled: set[str] = set()

    def today(self) -> date:
        return self.as_of or datetime.now(ET).date()

    def instances(self) -> list[str]:
        return [name for name in ("claude", "codex") if (self.root / name / "ticks").is_dir()]

    def catalog(self, instance: str) -> Row:
        sessions = recent_sessions(self.root, self.cache_dir, instance, self.today())
        for window in sessions:
            path = self.root / instance / "ticks" / f"ticks_{window['date']}.jsonl"
            window["has_data"] = path.exists() and path.stat().st_size > 0
            window["has_candles"] = (
                self.cache_dir / "candles" / f"QQQ_{window['date']}.json"
            ).exists()
        return {
            "sessions": sessions,
            "instances": self.instances(),
            "instance": instance,
            "sync_status": self.sync_status,
            "today": self.today().isoformat(),
        }

    def paths(self, day: str, instance: str) -> dict[str, Path]:
        base = self.root / instance
        return {
            "ticks": base / "ticks" / f"ticks_{day}.jsonl",
            "scenarios": base / "scenarios" / f"scenarios_{day}.jsonl",
            "orders": base / "orders" / f"orders_{day}.jsonl",
            "traces": base / "traces" / f"trace_{day}.md",
            "thesis": base / "daily_thesis" / f"thesis_{day}.md",
        }

    def session(self, day: str, instance: str) -> Row:
        paths = self.paths(day, instance)
        dependencies = [
            *paths.values(),
            self.cache_dir / "calendar.json",
            self.cache_dir / "candles" / f"QQQ_{day}.json",
        ]
        signature = tuple(
            (p.stat().st_mtime_ns, p.stat().st_size) if p.exists() else None for p in dependencies
        )
        with self._lock:
            cached = self._cache.get((day, instance))
            if cached and cached[0] == signature:
                return cached[1]
            result = self.build_session(day, instance, paths)
            self._cache[(day, instance)] = (signature, result)
            if len(self._cache) > 24:
                self._cache.pop(next(iter(self._cache)))
            return result

    def build_session(self, day: str, instance: str, paths: dict[str, Path]) -> Row:
        warnings: list[str] = []
        window = session_window(self.cache_dir, day)
        candles, origin = load_candles(self.cache_dir, window, warnings)
        ticks = usable_ticks(read_jsonl(paths["ticks"], self.root, warnings), window)
        events = read_jsonl(paths["scenarios"], self.root, warnings)
        scenarios = reconstruct_scenarios(events, day, instance, window["close"])
        decisions = read_decisions(paths["traces"], self.root, day, warnings)
        link_decisions(decisions, scenarios)
        fills, positions = read_fills(
            read_jsonl(paths["orders"], self.root, warnings), scenarios, decisions
        )
        add_outcomes(scenarios, candles)
        if not window["calendar_verified"]:
            warnings.append(
                "Alpaca calendar unavailable: showing recorded session dates with unverified "
                "09:30 to 16:00 bounds."
            )
        return {
            **window,
            "instance": instance,
            "symbol": "QQQ",
            "candles": candles,
            "price_source": origin,
            "prices": [
                {"time": t["time"], "value": t["price"], "source": t["source"]} for t in ticks
            ],
            "indicators": indicator_series(ticks),
            "scenarios": scenarios,
            "decisions": decisions,
            "fills": fills,
            "positions": positions,
            "warnings": warnings,
            "thesis": read_text(paths["thesis"], warnings),
            "thesis_source": source(paths["thesis"], self.root),
            "last_updated": max((t["time"] for t in ticks), default=None),
            "stats": session_stats(ticks, fills),
            "indicator_basis": (
                "Logged observations at tick time; gaps are preserved. "
                "Not recomputed from chart candles."
            ),
        }

    def synchronize(self, online: bool = True) -> None:
        """Only this worker writes the app's own cache; source logs remain read-only."""
        messages = []
        try:
            archive_snapshot(self.root, self.cache_dir)
        except (OSError, ValueError, KeyError) as exc:
            logger.warning("Snapshot archive failed: %s", exc)
            messages.append("Snapshot archive unavailable")
        if online and credentials("calendar") and self._calendar_day != self.today():
            try:
                sync_calendar(self.cache_dir, self.today())
                self._calendar_day = self.today()
            except Exception as exc:
                logger.warning("Alpaca calendar unavailable: %s", exc)
                messages.append("Alpaca calendar unavailable; using local records")
        if online and credentials("bars"):
            messages.extend(self.sync_bars())
        self.sync_status = (
            " · ".join(messages)
            if messages
            else (
                "Alpaca calendar and local data ready"
                if self._calendar_day
                else "Local logs · Alpaca credentials unavailable"
            )
        )

    def sync_bars(self) -> list[str]:
        errors = []
        sessions = {
            s["date"]: s
            for instance in self.instances()
            for s in self.catalog(instance)["sessions"]
        }
        for day, window in sessions.items():
            if not window["calendar_verified"] or (
                day in self._backfilled and day != self.today().isoformat()
            ):
                continue
            try:
                backfill_candles(self.cache_dir, window)
                self._backfilled.add(day)
            except Exception as exc:
                logger.warning("Candle backfill %s failed: %s", day, exc)
                errors.append(f"Candles unavailable for {day}")
        return errors


def usable_ticks(rows: list[Row], window: Row) -> list[Row]:
    ticks: dict[int, Row] = {}
    for row in timed_rows(rows):
        price = number(row.get("price"))
        if price is not None and price > 0 and window["open"] <= row["time"] < window["close"]:
            ticks[row["time"]] = {**row, "price": price}
    return [ticks[ts] for ts in sorted(ticks)]


def indicator_series(ticks: list[Row]) -> dict[str, list[Row]]:
    result: dict[str, list[Row]] = {}
    for field in INDICATORS:
        points: list[Row] = []
        for row in ticks:
            value = number(row.get(field))
            if points and row["time"] - points[-1]["time"] > 180:
                points.append({"time": points[-1]["time"] + 1})
            points.append({"time": row["time"], **({"value": value} if value is not None else {})})
        result[field] = points
    return result


def session_stats(ticks: list[Row], fills: list[Row]) -> Row:
    prices = [row["price"] for row in ticks]
    sells = [fill for fill in fills if fill["side"] == "sell"]
    return {
        "last": prices[-1] if prices else None,
        "change": prices[-1] - prices[0] if prices else None,
        "entries": len([f for f in fills if f["side"] == "buy"]),
        "exits": len(sells),
        "realized_pnl": round(sum(f["pnl"] for f in sells if f["pnl"] is not None), 2),
        "pnl_complete": all(f["pnl"] is not None for f in sells),
        "observations": len(ticks),
    }
