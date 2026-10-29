"""Triple-barrier labels and the class-balance audits applied to them.

Two rule sets follow the audit this was taken from. A hard gate checks the upper and lower
shares against [0.05, 0.80] in every year and fails the audit when one falls outside. A
diagnostic checks all three shares against [0.10, 0.70] and only warns. The chop check is
separate: a vertical (timeout) share above 0.40 over the whole sample means the barriers are
too far apart for the holding period.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

UPPER, LOWER, VERTICAL = "upper", "lower", "vertical"


def triple_barrier_labels(
    bars: pd.DataFrame,
    upper_pct: float,
    lower_pct: float,
    max_bars: int,
) -> pd.Series:
    """First barrier touched after each bar's close; a bar touching both counts as lower."""
    close = bars["close"].to_numpy()
    high = bars["high"].to_numpy()
    low = bars["low"].to_numpy()
    labels = np.full(len(close), None, dtype=object)
    for t in range(len(close) - max_bars):
        upper = close[t] * (1 + upper_pct / 100)
        lower = close[t] * (1 - lower_pct / 100)
        labels[t] = VERTICAL
        for i in range(t + 1, t + max_bars + 1):
            if low[i] <= lower:
                labels[t] = LOWER
                break
            if high[i] >= upper:
                labels[t] = UPPER
                break
    return pd.Series(labels, index=bars.index, name="barrier_hit")


@dataclass(frozen=True)
class BalanceRules:
    min_share: float = 0.05
    max_share: float = 0.80
    hard_gate: bool = True


HARD_GATE = BalanceRules()
DIAGNOSTIC = BalanceRules(min_share=0.10, max_share=0.70, hard_gate=False)
CHOP_THRESHOLD = 0.40


@dataclass(frozen=True)
class YearBalance:
    year: int
    rows: int
    upper: float
    lower: float
    vertical: float
    status: str


def balance_by_year(
    labels: pd.Series,
    timestamps: pd.Series,
    rules: BalanceRules,
) -> list[YearBalance]:
    frame = pd.DataFrame({"label": labels, "year": pd.to_datetime(timestamps).dt.year})
    rows = []
    for year, group in frame.dropna().groupby("year"):
        shares = group["label"].value_counts(normalize=True)
        upper, lower, vertical = (float(shares.get(k, 0.0)) for k in (UPPER, LOWER, VERTICAL))
        checked = [upper, lower] if rules.hard_gate else [upper, lower, vertical]
        balanced = all(rules.min_share <= s <= rules.max_share for s in checked)
        status = "PASS" if balanced else ("FAIL" if rules.hard_gate else "WARN")
        rows.append(YearBalance(int(year), len(group), upper, lower, vertical, status))
    return rows


def vertical_share(labels: pd.Series) -> float:
    """Share of labelled bars that timed out; compare against CHOP_THRESHOLD."""
    known = labels.dropna()
    return float((known == VERTICAL).mean()) if len(known) else 0.0
