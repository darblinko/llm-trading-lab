"""Read-only HTTP server: static frontend plus two JSON endpoints (stdlib only)."""

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from claude_review.payload_types import DayPayload

logger = logging.getLogger(__name__)

DAY_PATH = re.compile(r"^/api/day/(\d{4}-\d{2}-\d{2})$")


@dataclass(frozen=True)
class AppContext:
    """Everything a request needs; injected so tests can replace each piece."""

    static_dir: Path
    list_days: Callable[[], list[str]]
    build_day: Callable[[date, bool], DayPayload]
    today: Callable[[], date]


class ReviewRequestHandler(SimpleHTTPRequestHandler):
    """Serves static files from static_dir and the /api/* JSON endpoints."""

    context: AppContext

    def __init__(self, *args: object, context: AppContext, **kwargs: object) -> None:
        self.context = context
        super().__init__(*args, directory=str(context.static_dir), **kwargs)  # type: ignore[arg-type]

    def do_GET(self) -> None:
        url = urlsplit(self.path)
        if url.path == "/api/days":
            self._send_days()
        elif url.path.startswith("/api/"):
            self._send_day(url.path, parse_qs(url.query))
        else:
            super().do_GET()

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def log_message(self, format: str, *args: object) -> None:
        logger.info("%s %s", self.address_string(), format % args)

    def _send_days(self) -> None:
        today_text = self.context.today().isoformat()
        days = [{"date": day, "is_today": day == today_text} for day in self.context.list_days()]
        self._send_json(HTTPStatus.OK, {"days": days})

    def _send_day(self, path: str, query: dict[str, list[str]]) -> None:
        session_date = _parse_day_path(path)
        if session_date is None:
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"Unknown endpoint {path}"})
            return
        if session_date.isoformat() not in self.context.list_days():
            self._send_json(HTTPStatus.NOT_FOUND, {"error": f"No session logs for {session_date}"})
            return
        refresh = query.get("refresh", ["0"])[0] == "1"
        try:
            payload = self.context.build_day(session_date, refresh)
        except Exception as error:
            logger.exception("Building payload for %s failed", session_date)
            message = (
                f"Building {session_date} failed ({type(error).__name__}); see the server log."
            )
            self._send_json(HTTPStatus.INTERNAL_SERVER_ERROR, {"error": message})
            return
        self._send_json(HTTPStatus.OK, payload)

    def _send_json(self, status: HTTPStatus, body: object) -> None:
        encoded = json.dumps(body, allow_nan=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)


def _parse_day_path(path: str) -> date | None:
    match = DAY_PATH.match(path)
    if match is None:
        return None
    try:
        return date.fromisoformat(match.group(1))
    except ValueError:
        return None


def make_server(context: AppContext, host: str, port: int) -> ThreadingHTTPServer:
    """Bind the server; call serve_forever() on the result."""
    handler = partial(ReviewRequestHandler, context=context)
    return ThreadingHTTPServer((host, port), handler)
