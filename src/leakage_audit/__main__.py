"""Audit a bar file for look-ahead leaks and write a markdown report.

Usage: python -m leakage_audit --data data/sample/bars_1min.csv [--plant-leaks]
       [--purge-bars N] [--out report.md] [--fail-on-leak]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from leakage_audit.demo import clean_features, feature_columns, leaky_features
from leakage_audit.report import render_markdown, run_audit
from walkforward.data import load_bars
from walkforward.folds import generate_folds
from walkforward.labels import add_forward_returns

TARGET_HORIZON = 5
LABEL_HORIZON = 10


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Look-ahead leakage audit")
    parser.add_argument("--data", required=True, type=Path)
    parser.add_argument("--plant-leaks", action="store_true")
    parser.add_argument("--purge-bars", type=int, default=0)
    parser.add_argument("--out", type=Path)
    parser.add_argument("--fail-on-leak", action="store_true")
    args = parser.parse_args(argv)

    bars = add_forward_returns(load_bars(args.data), (TARGET_HORIZON,))
    feature_fn = leaky_features if args.plant_leaks else clean_features
    folds = generate_folds(bars, 30, 5, purge_bars=args.purge_bars)
    result = run_audit(
        bars,
        feature_fn,
        feature_columns(args.plant_leaks),
        f"fwd_return_{TARGET_HORIZON}",
        folds,
        LABEL_HORIZON,
        barrier=(0.3, 0.3, 30),
    )
    title = "Leakage audit" + (" (planted leaks)" if args.plant_leaks else "")
    report = render_markdown(result, title)
    if args.out:
        args.out.write_text(report)
    print(report)
    return 1 if args.fail_on_leak and result.leak_found else 0


if __name__ == "__main__":
    raise SystemExit(main())
