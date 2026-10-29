#!/usr/bin/env python3
"""Launch Codex Review App without importing or starting the trading system."""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

import uvicorn

APP_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_ROOT / "backend"))

from review_app.api import create_app  # noqa: E402
from review_app.market import archive_snapshot, credentials  # noqa: E402
from review_app.store import ReviewStore  # noqa: E402

logger = logging.getLogger("review_app")
SAMPLE_LOGS = APP_ROOT.parent / "sample-session" / "logs"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--logs", type=Path, default=SAMPLE_LOGS)
    parser.add_argument(
        "--ticks-dir", type=Path, help="A logs/<instance>/ticks directory; infers the log root"
    )
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, help="Anchor the six-session window to YYYY-MM-DD"
    )
    parser.add_argument(
        "--sync-only",
        action="store_true",
        help="Cache Alpaca calendar/bars and the shared snapshot, then exit",
    )
    parser.add_argument(
        "--offline", action="store_true", help="Use local data without Alpaca requests"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logging.basicConfig(level=logging.INFO)
    offline = args.offline
    if not offline and credentials("calendar") is None and credentials("bars") is None:
        logger.info("ALPACA_API_KEY and ALPACA_API_SECRET not set; running offline")
        offline = True
    root = args.ticks_dir.resolve().parent.parent if args.ticks_dir else args.logs.resolve()
    store = ReviewStore(root, APP_ROOT / "data", args.as_of)
    if args.sync_only:
        store.synchronize(online=not offline)
        print(store.sync_status)
        return
    if offline:
        archive_snapshot(root, store.cache_dir)
    app = create_app(store, APP_ROOT / "web/dist", online=not offline)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
