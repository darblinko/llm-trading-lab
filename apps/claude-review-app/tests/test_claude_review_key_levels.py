"""Tests for claude_review.key_levels."""

import copy

import pandas as pd
from claude_review.key_levels import build_key_levels
from claude_review.payload_types import KeyLevel


def _tick_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "tick": 300,
        "timestamp": "2026-09-23T15:29:00-04:00",
        "price": 745.0,
        "prev_day_high": 748.35,
        "prev_day_low": 740.94,
        "prev_day_close": 747.46,
        "overnight_high": 749.08,
        "overnight_low": 744.69,
        "d_h4": 751.54,
        "d_h3": 749.5,
        "d_pivot": 745.58,
        "d_l3": 745.42,
        "d_l4": 743.38,
        "w_h3": 727.43,
    }
    row.update(overrides)
    return row


def _day_minute(spike_at_945: float = 760.0) -> pd.DataFrame:
    """RTH 1-min bars for 2026-09-23 with a flat 745 tape except controlled extremes."""
    index = pd.date_range("2026-09-23 09:30", "2026-09-23 15:59", freq="1min")
    frame = pd.DataFrame(
        {"open": 745.0, "high": 745.5, "low": 744.5, "close": 745.0, "volume": 1000.0},
        index=index,
    )
    frame.loc[pd.Timestamp("2026-09-23 09:37"), "high"] = 747.13
    frame.loc[pd.Timestamp("2026-09-23 09:44"), "low"] = 744.451
    frame.loc[pd.Timestamp("2026-09-23 09:45"), "high"] = spike_at_945
    frame.loc[pd.Timestamp("2026-09-23 09:45"), "low"] = 700.0
    return frame


def _by_label(levels: list[KeyLevel]) -> dict[str, KeyLevel]:
    return {level["label"]: level for level in levels}


class TestTickLevels:
    def test_levels_from_last_tick_row(self) -> None:
        rows = [_tick_row(prev_day_high=1.0, tick=1), _tick_row()]
        levels = _by_label(build_key_levels(rows, _day_minute()))
        assert levels["PDH"] == {"label": "PDH", "price": 748.35, "group": "prior_day"}
        assert levels["PDL"]["price"] == 740.94 and levels["PDC"]["price"] == 747.46
        assert levels["ONH"] == {"label": "ONH", "price": 749.08, "group": "overnight"}
        assert levels["ONL"]["price"] == 744.69
        assert levels["H3"] == {"label": "H3", "price": 749.5, "group": "camarilla"}
        assert levels["H4"]["price"] == 751.54 and levels["L3"]["price"] == 745.42
        assert levels["L4"]["price"] == 743.38 and levels["Pivot"]["price"] == 745.58

    def test_order_is_prior_day_overnight_camarilla_opening_range(self) -> None:
        labels = [level["label"] for level in build_key_levels([_tick_row()], _day_minute())]
        assert labels == [
            "PDH",
            "PDL",
            "PDC",
            "ONH",
            "ONL",
            "H4",
            "H3",
            "Pivot",
            "L3",
            "L4",
            "ORH",
            "ORL",
        ]

    def test_null_and_missing_values_are_skipped(self) -> None:
        row = _tick_row(overnight_high=None, d_h4=float("nan"))
        del row["overnight_low"]
        labels = {level["label"] for level in build_key_levels([row], _day_minute())}
        assert not {"ONH", "ONL", "H4"} & labels
        assert "PDH" in labels

    def test_null_in_last_row_falls_back_to_latest_logged_value(self) -> None:
        rows = [_tick_row(d_pivot=745.58), _tick_row(d_pivot=None)]
        assert _by_label(build_key_levels(rows, _day_minute()))["Pivot"]["price"] == 745.58

    def test_non_numeric_values_are_skipped(self) -> None:
        row = _tick_row(prev_day_high="748.35", prev_day_low=True)
        labels = {level["label"] for level in build_key_levels([row], _day_minute())}
        assert not {"PDH", "PDL"} & labels

    def test_no_tick_rows_gives_opening_range_only(self) -> None:
        labels = [level["label"] for level in build_key_levels([], _day_minute())]
        assert labels == ["ORH", "ORL"]

    def test_inputs_are_not_modified(self) -> None:
        rows = [_tick_row(d_pivot=None)]
        day = _day_minute()
        rows_before, day_before = copy.deepcopy(rows), day.copy()
        build_key_levels(rows, day)
        assert rows == rows_before
        pd.testing.assert_frame_equal(day, day_before)


class TestOpeningRange:
    def test_logged_opening_range_is_preferred(self) -> None:
        row = _tick_row(opening_range_high=747.0, opening_range_low=744.96)
        levels = _by_label(build_key_levels([row], _day_minute()))
        assert levels["ORH"] == {"label": "ORH", "price": 747.0, "group": "opening_range"}
        assert levels["ORL"] == {"label": "ORL", "price": 744.96, "group": "opening_range"}

    def test_logged_opening_range_needs_no_day_bars(self) -> None:
        row = _tick_row(opening_range_high=747.0, opening_range_low=744.96)
        labels = [level["label"] for level in build_key_levels([row], _day_minute().iloc[0:0])]
        assert labels[-2:] == ["ORH", "ORL"]

    def test_null_logged_value_falls_back_to_day_bars(self) -> None:
        row = _tick_row(opening_range_high=None, opening_range_low=744.96)
        levels = _by_label(build_key_levels([row], _day_minute()))
        assert levels["ORH"]["price"] == 747.13
        assert levels["ORL"]["price"] == 744.96

    def test_first_fifteen_minutes_only(self) -> None:
        levels = _by_label(build_key_levels([], _day_minute()))
        assert levels["ORH"] == {"label": "ORH", "price": 747.13, "group": "opening_range"}
        assert levels["ORL"] == {"label": "ORL", "price": 744.45, "group": "opening_range"}

    def test_missing_day_bars_gives_no_opening_range(self) -> None:
        empty = _day_minute().iloc[0:0]
        labels = {level["label"] for level in build_key_levels([_tick_row()], empty)}
        assert not {"ORH", "ORL"} & labels

    def test_day_starting_after_opening_range_gives_none(self) -> None:
        late = _day_minute().loc["2026-09-23 10:00":]
        labels = {level["label"] for level in build_key_levels([], late)}
        assert labels == set()

    def test_day_ending_inside_opening_range_gives_none(self) -> None:
        early = _day_minute().loc[:"2026-09-23 09:40"]
        labels = {level["label"] for level in build_key_levels([], early)}
        assert labels == set()

    def test_day_ending_on_final_opening_range_minute_gives_range(self) -> None:
        early = _day_minute().loc[:"2026-09-23 09:44"]
        levels = _by_label(build_key_levels([], early))
        assert levels["ORH"]["price"] == 747.13
        assert levels["ORL"]["price"] == 744.45
