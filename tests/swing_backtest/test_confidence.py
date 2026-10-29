"""Confidence table: target-hit rates with hierarchical shrinkage."""

import json
from datetime import date, timedelta

import pytest

from swing_backtest.confidence import (
    ConfidenceRow,
    confidence_table,
    confidence_to_json,
    context_key,
    shrink,
)
from swing_backtest.domain import TradeDirection
from swing_backtest.trades import ExitReason, TradeResult

BULL = (("regime", "bull"), ("weekly_trend", "up"))
BEAR = (("weekly_trend", "down"), ("regime", "bear"))


def _events(variant: str, n: int, hits: int, context=BULL, family: str = "fam"):
    rows = []
    for i in range(n):
        entry = date(2024, 1, 1) + timedelta(days=i)
        reason = ExitReason.TARGET if i < hits else ExitReason.STOP
        rows.append(
            TradeResult(
                candidate_id=f"{family}-{variant}-{context_key(context)}-{i}",
                ticker="AAA",
                family=family,
                variant=variant,
                direction=TradeDirection.CALL,
                as_of=entry,
                trigger_date=entry,
                entry_date=entry,
                entry_price=100.0,
                stop_price=95.0,
                target_price=110.0,
                exit_date=entry,
                exit_price=110.0,
                exit_reason=reason,
                r_multiple=2.0 if reason == ExitReason.TARGET else -1.0,
                bars_held=1,
                max_hold_bars=10,
                context=context,
            )
        )
    return rows


def _row(rows, variant=None, context=None) -> ConfidenceRow:
    return next(r for r in rows if r.variant == variant and r.context == context)


def test_context_key_sorts_names():
    assert context_key(BEAR) == "regime=bear;weekly_trend=down"
    assert context_key(()) == ""


def test_shrink_formula():
    assert shrink(6, 10, 0.375, 20.0) == pytest.approx(13.5 / 30.0)
    assert shrink(3, 10, 0.9, 0.0) == pytest.approx(0.3)


def test_three_level_shrinkage_arithmetic():
    events = _events("a", 4, 4, BULL) + _events("a", 6, 2, BEAR) + _events("b", 30, 9, BULL)
    rows = confidence_table(events, prior_strength=20.0)

    family = _row(rows)
    assert (family.n, family.hits) == (40, 15)
    assert family.raw_rate == pytest.approx(0.375)
    assert family.shrunk_rate == pytest.approx(0.375)

    variant_a = _row(rows, "a")
    assert (variant_a.n, variant_a.hits, variant_a.raw_rate) == (10, 6, 0.6)
    assert variant_a.shrunk_rate == pytest.approx((6 + 20 * 0.375) / 30)
    variant_b = _row(rows, "b")
    assert variant_b.shrunk_rate == pytest.approx((9 + 20 * 0.375) / 50)

    bucket = _row(rows, "a", "regime=bull;weekly_trend=up")
    assert (bucket.n, bucket.hits, bucket.raw_rate) == (4, 4, 1.0)
    assert bucket.shrunk_rate == pytest.approx((4 + 20 * variant_a.shrunk_rate) / 24)
    bear = _row(rows, "a", "regime=bear;weekly_trend=down")
    assert bear.shrunk_rate == pytest.approx((2 + 20 * variant_a.shrunk_rate) / 26)


def test_row_order_is_family_variant_then_buckets():
    events = _events("b", 3, 1) + _events("a", 2, 1, BEAR) + _events("a", 2, 2, BULL)
    events += _events("x", 1, 1, family="aaa")
    rows = confidence_table(events)
    assert [(r.family, r.variant, r.context) for r in rows] == [
        ("aaa", None, None),
        ("aaa", "x", None),
        ("aaa", "x", "regime=bull;weekly_trend=up"),
        ("fam", None, None),
        ("fam", "a", None),
        ("fam", "a", "regime=bear;weekly_trend=down"),
        ("fam", "a", "regime=bull;weekly_trend=up"),
        ("fam", "b", None),
        ("fam", "b", "regime=bull;weekly_trend=up"),
    ]


def test_zero_prior_strength_gives_raw_rates():
    rows = confidence_table(_events("a", 5, 2) + _events("b", 5, 4), prior_strength=0.0)
    assert all(row.shrunk_rate == pytest.approx(row.raw_rate) for row in rows)


def test_empty_and_invalid_input():
    assert confidence_table([]) == ()
    with pytest.raises(ValueError):
        confidence_table(_events("a", 2, 1), prior_strength=-1.0)


def test_json_round_trip():
    rows = confidence_table(_events("a", 4, 3) + _events("a", 3, 0, BEAR))
    payload = confidence_to_json(rows)
    assert json.loads(json.dumps(payload)) == payload
    assert payload[0] == {
        "family": "fam",
        "variant": None,
        "context": None,
        "n": 7,
        "hits": 3,
        "raw_rate": pytest.approx(3 / 7),
        "shrunk_rate": pytest.approx(3 / 7),
    }
    assert [ConfidenceRow(**item) for item in payload] == list(rows)
