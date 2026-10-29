"""Write synthetic one-minute bars to data/sample/bars_1min.csv (no market data involved)."""

import argparse
from pathlib import Path

from walkforward.synthetic import synthetic_minute_bars


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sessions", type=int, default=45)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--out", type=Path, default=Path("data/sample/bars_1min.csv"))
    args = parser.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    bars = synthetic_minute_bars(args.sessions, args.seed)
    bars.to_csv(args.out, index=False)
    print(f"wrote {len(bars)} bars over {args.sessions} sessions to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
