from __future__ import annotations

from conftest import scenario_event, ts
from fastapi.testclient import TestClient
from review_app.api import create_app
from review_app.scenarios import reconstruct_scenarios
from review_app.store import indicator_series
from review_app.trades import read_fills


def order(order_id: str, clock: str, qty: int, price: float, side: str = "buy") -> dict:
    return {
        "client_order_id": order_id,
        "timestamp": f"2026-09-24T{clock}:00",
        "action": "fill",
        "qty_filled": qty,
        "avg_fill_price": price,
        "symbol": "QQQ260924C00100000",
        "side": side,
        "source": f"orders:{order_id}:{clock}",
        "metadata": {"scenario_label": "Support reclaim"},
    }


def test_partial_fills_are_incremental_and_exit_uses_weighted_cost() -> None:
    scenarios = reconstruct_scenarios(
        [scenario_event("created", "09:29")], "2026-09-24", "claude", ts("16:00")
    )
    records = [
        order("buy", "09:31", 2, 1),
        order("buy", "09:32", 3, 1.2),
        order("buy", "09:33", 3, 1.2),
        order("sell", "09:40", 2, 2, "sell"),
    ]
    fills, positions = read_fills(records, scenarios, [])
    assert [f["qty"] for f in fills] == [2, 1, 2]
    assert fills[1]["price"] == 1.6
    assert fills[2]["pnl"] == 160
    assert fills[2]["scenario_id"] == scenarios[0]["id"]
    assert positions[0]["qty"] == 1
    assert round(positions[0]["average_price"], 2) == 1.2


def test_exit_without_entry_is_not_assigned_fabricated_pnl() -> None:
    fills, positions = read_fills([order("sell", "10:00", 4, 2, "sell")], [], [])
    assert fills[0]["pnl"] is None
    assert fills[0]["warnings"]
    assert not positions


def test_unfilled_intents_never_create_trade_markers() -> None:
    row = order("intent", "10:00", 0, 2)
    row["action"] = "submitted"
    assert read_fills([row], [], []) == ([], [])


def test_indicator_gaps_are_not_forward_filled() -> None:
    values = indicator_series([{"time": 1000, "rsi": 40}, {"time": 1600, "rsi": 60}])["rsi"]
    assert values == [{"time": 1000, "value": 40}, {"time": 1001}, {"time": 1600, "value": 60}]


def test_api_is_read_only_and_exposes_actual_sources(store) -> None:
    before = {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}
    with TestClient(create_app(store, sync=False)) as client:
        assert client.get("/api/health").json()["app"] == "codex-review-app"
        data = client.get("/api/sessions/2026-09-24").json()
        assert data["candles"] == []
        assert data["prices"][0]["value"] == 100
        assert data["prices"][0]["source"].endswith("ticks_2026-09-24.jsonl:1")
        assert client.post("/api/sessions/2026-09-24").status_code == 405
        assert client.get("/api/sessions/2026-09-01").status_code == 404
        assert client.get("/api/sessions/not-a-date").status_code == 422
        assert client.get("/api/sessions?instance=../shared").status_code == 422
    assert before == {p: p.read_bytes() for p in store.root.rglob("*") if p.is_file()}


def test_missing_instance_does_not_reuse_other_instance_data(store) -> None:
    with TestClient(create_app(store, sync=False)) as client:
        assert client.get("/api/sessions?instance=codex").json()["sessions"] == []
        assert client.get("/api/sessions/2026-09-24?instance=codex").status_code == 404


def test_session_cache_updates_after_new_tick(store) -> None:
    old = store.session("2026-09-24", "claude")
    assert store.session("2026-09-24", "claude") is old
    path = store.root / "claude/ticks/ticks_2026-09-24.jsonl"
    with path.open("a") as file:
        file.write('{"timestamp":"2026-09-24T09:36:00","price":103}\n')
    new = store.session("2026-09-24", "claude")
    assert new["stats"]["last"] == 103
    assert new is not old


def test_offline_sync_does_not_call_alpaca(store, monkeypatch) -> None:
    monkeypatch.setattr("review_app.store.credentials", lambda _: ("test", "test", "url"))
    monkeypatch.setattr(
        "review_app.store.sync_calendar",
        lambda *_: (_ for _ in ()).throw(AssertionError("Network called")),
    )
    store.synchronize(online=False)
    assert store.session("2026-09-24", "claude")["prices"]
