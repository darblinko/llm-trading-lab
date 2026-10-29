"""HTTP contract tests for claude_review.server with injected fakes."""

import json
import threading
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import urlopen

import pytest
from claude_review.server import AppContext, make_server

LISTED_DAYS = ["2026-09-24", "2026-09-23"]


class FakeDayBuilder:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[tuple[date, bool]] = []
        self.fail = fail

    def __call__(self, session_date: date, refresh: bool) -> dict:
        self.calls.append((session_date, refresh))
        if self.fail:
            raise RuntimeError("trace unreadable")
        return {"date": session_date.isoformat(), "bars": []}


def _start(context: AppContext) -> tuple[str, threading.Thread, object]:
    server = make_server(context, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return f"http://127.0.0.1:{server.server_address[1]}", thread, server


@pytest.fixture
def static_dir(tmp_path: Path) -> Path:
    static = tmp_path / "static"
    static.mkdir()
    (static / "index.html").write_text("<html>review</html>")
    (tmp_path / "secret.txt").write_text("outside static")
    return static


def _serve(static_dir: Path, builder: FakeDayBuilder) -> Iterator[str]:
    context = AppContext(
        static_dir=static_dir,
        list_days=lambda: list(LISTED_DAYS),
        build_day=builder,
        today=lambda: date(2026, 9, 24),
    )
    base_url, thread, server = _start(context)
    yield base_url
    server.shutdown()
    server.server_close()
    thread.join(timeout=5)


@pytest.fixture
def builder() -> FakeDayBuilder:
    return FakeDayBuilder()


@pytest.fixture
def base_url(static_dir: Path, builder: FakeDayBuilder) -> Iterator[str]:
    yield from _serve(static_dir, builder)


def _get_json(url: str) -> tuple[int, dict]:
    try:
        with urlopen(url, timeout=5) as response:
            return response.status, json.loads(response.read())
    except HTTPError as error:
        return error.code, json.loads(error.read())


def test_days_endpoint_flags_today(base_url: str) -> None:
    status, body = _get_json(f"{base_url}/api/days")
    assert status == 200
    assert body == {
        "days": [
            {"date": "2026-09-24", "is_today": True},
            {"date": "2026-09-23", "is_today": False},
        ]
    }


def test_day_endpoint_returns_payload_and_passes_refresh(
    base_url: str, builder: FakeDayBuilder
) -> None:
    status, body = _get_json(f"{base_url}/api/day/2026-09-23")
    assert status == 200
    assert body["date"] == "2026-09-23"
    _get_json(f"{base_url}/api/day/2026-09-24?refresh=1")
    assert builder.calls == [(date(2026, 9, 23), False), (date(2026, 9, 24), True)]


@pytest.mark.parametrize(
    "path", ["/api/day/2026-09-01", "/api/day/2026-13-45", "/api/day/..%2F..", "/api/nothing"]
)
def test_unknown_or_invalid_day_is_404(base_url: str, builder: FakeDayBuilder, path: str) -> None:
    status, body = _get_json(f"{base_url}{path}")
    assert status == 404
    assert "error" in body
    assert builder.calls == []


def test_builder_failure_is_500_with_error(static_dir: Path) -> None:
    for base in _serve(static_dir, FakeDayBuilder(fail=True)):
        status, body = _get_json(f"{base}/api/day/2026-09-24")
        assert status == 500
        assert body == {"error": "Building 2026-09-24 failed (RuntimeError); see the server log."}
        assert "trace unreadable" not in body["error"]


def test_static_files_served_and_confined(base_url: str) -> None:
    with urlopen(f"{base_url}/", timeout=5) as response:
        assert response.read() == b"<html>review</html>"
    with pytest.raises(HTTPError) as outside:
        urlopen(f"{base_url}/../secret.txt", timeout=5)
    assert outside.value.code == 404
