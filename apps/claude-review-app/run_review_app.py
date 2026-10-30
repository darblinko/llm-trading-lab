"""Start the session review app (read-only).

Usage: python3 run_review_app.py [--port 8765] [--log-dir DIR] [--bars-file FILE]

Both paths default to the synthetic sample in ../sample-session.
"""

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

APP_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(APP_DIR))

from claude_review.bars import bars_source_id, make_fetch  # noqa: E402
from claude_review.day_payload import DaySources, build_day_payload  # noqa: E402
from claude_review.log_files import list_session_days  # noqa: E402
from claude_review.payload_types import DayPayload  # noqa: E402
from claude_review.server import AppContext, make_server  # noqa: E402

logger = logging.getLogger("claude_review")

SESSION_DAY_LIMIT = 6
CACHE_DIR = APP_DIR / ".cache"
STATIC_DIR = APP_DIR / "static"
SAMPLE_DIR = APP_DIR.parent / "sample-session"


def today_et() -> date:
    return datetime.now(ZoneInfo("America/New_York")).date()


def build_context(log_dir: Path, bars_file: Path | None) -> AppContext:
    fetch = make_fetch(bars_file)

    def build_day(session_date: date, refresh: bool) -> DayPayload:
        sources = DaySources(
            log_dir=log_dir,
            cache_dir=CACHE_DIR,
            fetch=fetch,
            today=today_et(),
            bars_source=bars_source_id(bars_file),
        )
        return build_day_payload(session_date, sources, refresh)

    return AppContext(
        static_dir=STATIC_DIR,
        list_days=lambda: list_session_days(log_dir, SESSION_DAY_LIMIT),
        build_day=build_day,
        today=today_et,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Session review app (read-only).")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--log-dir", type=Path, default=SAMPLE_DIR / "logs" / "claude")
    parser.add_argument(
        "--bars-file",
        type=Path,
        default=SAMPLE_DIR / "market" / "QQQ_1m.jsonl",
        help="JSONL 1-min bars read before Alpaca; pass a missing path to use Alpaca only",
    )
    return parser.parse_args()


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    args = parse_args()
    if not args.log_dir.is_dir():
        sys.exit(f"Log directory not found: {args.log_dir}")
    CACHE_DIR.mkdir(exist_ok=True)
    server = make_server(build_context(args.log_dir, args.bars_file), "127.0.0.1", args.port)
    logger.info("Serving %s on http://127.0.0.1:%d", args.log_dir, args.port)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
