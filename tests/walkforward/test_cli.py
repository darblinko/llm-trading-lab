import importlib.util

import pytest

from walkforward import models
from walkforward.__main__ import main
from walkforward.synthetic import synthetic_minute_bars


def test_cli_writes_fold_and_trade_files(tmp_path, capsys):
    data = tmp_path / "bars.csv"
    synthetic_minute_bars(37, seed=1).to_csv(data, index=False)
    out_dir = tmp_path / "out"
    assert (
        main(
            ["--data", str(data), "--trees", "10", "--purge-bars", "10", "--out-dir", str(out_dir)]
        )
        == 0
    )
    assert "folds 1" in capsys.readouterr().out
    assert (out_dir / "folds.csv").exists() and (out_dir / "trades.csv").exists()


@pytest.mark.skipif(importlib.util.find_spec("xgboost") is not None, reason="xgboost installed")
def test_xgboost_factory_explains_missing_extra():
    with pytest.raises(ImportError, match="xgboost extra"):
        models.xgboost()
