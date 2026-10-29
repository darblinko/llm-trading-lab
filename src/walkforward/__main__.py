"""Walk-forward run on a bar file.

Usage: python -m walkforward --data data/sample/bars_1min.csv [--model rf|xgboost]
       [--purge-bars N] [--trees N] [--out-dir DIR]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from walkforward import models
from walkforward.backtest import WalkForwardConfig, run_walk_forward
from walkforward.data import load_bars
from walkforward.features import FEATURE_COLUMNS, build_features
from walkforward.labels import add_binary_label, add_forward_returns

THRESHOLD_PCT = 0.05


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Walk-forward classifier backtest")
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--model", choices=("rf", "xgboost"), default="rf")
    parser.add_argument("--purge-bars", type=int, default=0)
    parser.add_argument("--trees", type=int, default=100)
    parser.add_argument("--out-dir", type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = WalkForwardConfig(purge_bars=args.purge_bars)
    bars = add_forward_returns(load_bars(args.data), (config.horizon,))
    bars = build_features(add_binary_label(bars, config.horizon, THRESHOLD_PCT))
    factory = models.random_forest if args.model == "rf" else models.xgboost
    result = run_walk_forward(bars, factory({"n_estimators": args.trees}), FEATURE_COLUMNS, config)
    print(result.folds.to_string(index=False))
    print(f"folds {len(result.folds)}; mean AUC {result.folds['auc_roc'].mean():.4f}")
    print("trades: " + ", ".join(f"{k} {v}" for k, v in result.summary.items()))
    if args.out_dir:
        args.out_dir.mkdir(parents=True, exist_ok=True)
        result.folds.to_csv(args.out_dir / "folds.csv", index=False)
        result.trades.to_csv(args.out_dir / "trades.csv", index=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
