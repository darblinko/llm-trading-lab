import numpy as np
import pandas as pd
import pytest

from walkforward.data import load_bars, split_at
from walkforward.labels import add_binary_label, add_forward_returns
from walkforward.synthetic import BARS_PER_SESSION, synthetic_minute_bars


def test_load_bars_csv_adds_session_columns(tmp_path):
    path = tmp_path / "bars.csv"
    synthetic_minute_bars(3).to_csv(path, index=False)
    bars = load_bars(path)
    assert list(bars["session_id"].unique()) == [0, 1, 2]
    assert bars["minute_of_day"].min() == 570
    assert len(bars) == 3 * BARS_PER_SESSION


def test_load_bars_rejects_missing_columns_and_types(tmp_path):
    path = tmp_path / "bars.csv"
    synthetic_minute_bars(1).drop(columns=["volume"]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="volume"):
        load_bars(path)
    with pytest.raises(ValueError, match="unsupported"):
        load_bars(tmp_path / "bars.xlsx")


def test_split_at(bars):
    cutoff = str(bars["date"].unique()[10])
    train, holdout = split_at(bars, cutoff)
    assert train["date"].max() < holdout["date"].min()
    assert len(train) + len(holdout) == len(bars)


def test_forward_return_formula_and_tail(bars):
    out = add_forward_returns(bars, (5,))
    expected = (bars["close"].iloc[105] / bars["close"].iloc[100] - 1) * 100
    assert out["fwd_return_5"].iloc[100] == pytest.approx(expected)
    assert out["fwd_return_5"].iloc[-5:].isna().all()


def test_cross_session_targets_only_when_requested(bars):
    last_bar_of_first_session = BARS_PER_SESSION - 1
    crossing = add_forward_returns(bars, (10,))
    within = add_forward_returns(bars, (10,), within_session=True)
    assert not np.isnan(crossing["fwd_return_10"].iloc[last_bar_of_first_session])
    assert np.isnan(within["fwd_return_10"].iloc[last_bar_of_first_session])


def test_binary_label_is_nan_where_target_unknown(bars):
    out = add_binary_label(bars, 10, 0.05)
    assert out["label_binary"].iloc[-10:].isna().all()
    assert set(out["label_binary"].dropna().unique()) <= {0.0, 1.0}
    assert isinstance(out, pd.DataFrame)


def _rows(stamps):
    return pd.DataFrame(
        {"timestamp": stamps, "open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1}
    )


def test_offset_timestamps_across_dst_change_become_eastern_wall_time():
    from walkforward.data import add_session_columns

    out = add_session_columns(_rows(["2026-03-09T09:30:00-04:00", "2026-03-06T09:30:00-05:00"]))

    assert [str(d) for d in out["date"]] == ["2026-03-06", "2026-03-09"]
    assert out["minute_of_day"].tolist() == [570, 570]
    assert out["session_id"].tolist() == [0, 1]
    assert out["timestamp"].dt.tz is None


def test_utc_timestamps_are_converted_to_eastern_sessions():
    from walkforward.data import add_session_columns

    out = add_session_columns(_rows(["2026-01-07T01:00:00Z", "2026-01-07T14:30:00Z"]))

    assert [str(d) for d in out["date"]] == ["2026-01-06", "2026-01-07"]
    assert out["minute_of_day"].tolist() == [20 * 60, 9 * 60 + 30]


def test_tz_aware_datetime_column_is_converted():
    from walkforward.data import add_session_columns

    stamps = pd.to_datetime(["2026-07-01T13:30:00Z"], utc=True)
    out = add_session_columns(_rows(stamps))

    assert out["minute_of_day"].tolist() == [9 * 60 + 30]


def test_naive_timestamps_are_read_as_eastern_wall_time():
    from walkforward.data import add_session_columns

    out = add_session_columns(_rows(["2026-01-07 09:30:00"]))

    assert out["minute_of_day"].tolist() == [570]


def test_mixed_naive_and_offset_timestamps_are_rejected():
    from walkforward.data import add_session_columns

    with pytest.raises(ValueError, match="naive"):
        add_session_columns(_rows(["2026-01-07 09:30:00", "2026-01-07T09:31:00-05:00"]))
