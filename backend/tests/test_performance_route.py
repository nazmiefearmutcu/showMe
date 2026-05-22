"""Performance routes tests."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    import showme.bots.lifespan as lifespan
    lifespan._RUNNER = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def _create_bot(client, symbol="BTC/USDT"):
    r = client.post("/api/bots", json={
        "strategy_id": "s1", "credential_id": "c1", "exchange_id": "binance",
        "symbol": symbol, "timeframe": "1h", "tick_interval_seconds": 60,
    })
    return r.json()["id"]


def _push_signals(bot_id, signals):
    from showme.bots.store import BotStore
    from showme.bots.record import SignalEntry
    store = BotStore.fresh()
    rec = store.get(bot_id)
    for kind, price, ts in signals:
        rec = rec.append_signal(SignalEntry(
            bar_index=0, bar_time=ts, kind=kind, price=price,
            action="shadow", timestamp=ts,
        ))
    store.save(rec)


def test_leaderboard_empty(client):
    r = client.get("/api/bots/performance")
    assert r.status_code == 200
    assert r.json()["records"] == []


def test_leaderboard_with_two_bots(client):
    a = _create_bot(client, "BTC/USDT")
    b = _create_bot(client, "ETH/USDT")
    _push_signals(a, [
        ("entry", 100.0, "2026-05-22T10:00:00Z"),
        ("exit", 110.0, "2026-05-22T11:00:00Z"),
    ])
    _push_signals(b, [
        ("entry", 100.0, "2026-05-22T10:00:00Z"),
        ("exit", 95.0, "2026-05-22T11:00:00Z"),
    ])
    r = client.get("/api/bots/performance")
    body = r.json()
    assert len(body["records"]) == 2
    # Best first (positive PnL):
    assert body["records"][0]["bot_id"] == a
    assert body["records"][0]["total_pnl"] > 0
    assert body["records"][1]["bot_id"] == b
    assert body["records"][1]["total_pnl"] < 0


def test_bot_performance_detail(client):
    bid = _create_bot(client)
    _push_signals(bid, [
        ("entry", 100.0, "t1"),
        ("exit", 110.0, "t2"),
        ("entry", 100.0, "t3"),
        ("exit", 105.0, "t4"),
    ])
    r = client.get(f"/api/bots/{bid}/performance")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["bot_id"] == bid
    assert body["metrics"]["trade_count"] == 2
    assert body["metrics"]["total_pnl"] > 0
    assert len(body["trades"]) == 2
    assert len(body["equity_curve"]) >= 3  # start + 2 trades


def test_bot_performance_404(client):
    r = client.get("/api/bots/no-such-id/performance")
    assert r.status_code == 404
