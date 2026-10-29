"""Key price levels for the review chart.

Every level is read from the tick log, which records the values the trading
agent used. When the log has no opening range, it is computed from the
session's 1-min bars (09:30 to 09:45 ET window), as of the end of the last bar.
"""

from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta
from typing import NamedTuple

import pandas as pd

from claude_review.market_helpers import compute_opening_range
from claude_review.payload_types import KeyLevel

logger = logging.getLogger(__name__)


class LevelField(NamedTuple):
    key: str
    label: str
    group: str


LEVEL_FIELDS = (
    LevelField("prev_day_high", "PDH", "prior_day"),
    LevelField("prev_day_low", "PDL", "prior_day"),
    LevelField("prev_day_close", "PDC", "prior_day"),
    LevelField("overnight_high", "ONH", "overnight"),
    LevelField("overnight_low", "ONL", "overnight"),
    LevelField("d_h4", "H4", "camarilla"),
    LevelField("d_h3", "H3", "camarilla"),
    LevelField("d_pivot", "Pivot", "camarilla"),
    LevelField("d_l3", "L3", "camarilla"),
    LevelField("d_l4", "L4", "camarilla"),
    LevelField("opening_range_high", "ORH", "opening_range"),
    LevelField("opening_range_low", "ORL", "opening_range"),
)


def build_key_levels(
    tick_rows: list[dict[str, object]], day_minute: pd.DataFrame
) -> list[KeyLevel]:
    """Logged levels in LEVEL_FIELDS order; levels without any value are left out."""
    logged = {field.key: _latest_price(tick_rows, field.key) for field in LEVEL_FIELDS}
    missing = [key for key, price in logged.items() if price is None]
    if missing and tick_rows:
        logger.info("Tick log has no value for key levels %s", ", ".join(missing))
    prices = {
        **_computed_opening_range(day_minute),
        **{key: price for key, price in logged.items() if price is not None},
    }
    return [
        KeyLevel(label=field.label, price=prices[field.key], group=field.group)
        for field in LEVEL_FIELDS
        if prices.get(field.key) is not None
    ]


def _latest_price(tick_rows: list[dict[str, object]], key: str) -> float | None:
    """The latest numeric value logged for key.

    Rows written while the shared snapshot was stale carry null levels, so the
    final row alone can be empty even though the levels were in use that day.
    """
    for row in reversed(tick_rows):
        value = row.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            return float(value)
    return None


def _computed_opening_range(day_minute: pd.DataFrame) -> dict[str, float | None]:
    if day_minute.empty:
        return {"opening_range_high": None, "opening_range_low": None}
    high, low = compute_opening_range(day_minute, _bars_end(day_minute))
    return {"opening_range_high": high, "opening_range_low": low}


def _bars_end(day_minute: pd.DataFrame) -> datetime:
    """Close time of the last 1-min bar: the moment the review data reaches."""
    last_start: pd.Timestamp = day_minute.index.max()
    return last_start.to_pydatetime() + timedelta(minutes=1)
