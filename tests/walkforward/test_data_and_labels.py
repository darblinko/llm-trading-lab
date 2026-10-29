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
