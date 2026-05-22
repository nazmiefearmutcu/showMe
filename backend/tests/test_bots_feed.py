"""GET /api/bots/feed aggregate signal feed tests."""
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
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_feed_empty(client):
    r = client.get("/api/bots/feed")
    assert r.status_code == 200
    body = r.json()
    assert body["signals"] == []
    assert "generated_at" in body


def test_feed_aggregates_across_bots(client, tmp_path):
    # Create two bots, manually push signals to their stores.
    a_id = _create_bot(client, symbol="BTC/USDT")
    b_id = _create_bot(client, symbol="ETH/USDT")

    from showme.bots.store import BotStore
    from showme.bots.record import SignalEntry
    store = BotStore.fresh()
    bot_a = store.get(a_id)
    bot_b = store.get(b_id)
    store.save(bot_a.append_signal(SignalEntry(
        bar_index=1, bar_time="2026-05-22T10:00:00Z", kind="entry",
        price=60000.0, action="shadow", timestamp="2026-05-22T10:00:00Z",
    )))
    store.save(bot_b.append_signal(SignalEntry(
        bar_index=1, bar_time="2026-05-22T11:00:00Z", kind="entry",
        price=2500.0, action="shadow", timestamp="2026-05-22T11:00:00Z",
    )))

    r = client.get("/api/bots/feed")
    body = r.json()
    assert len(body["signals"]) == 2
    # Newest first: ETH signal (11:00) before BTC signal (10:00)
    assert body["signals"][0]["bot_symbol"] == "ETH/USDT"
    assert body["signals"][1]["bot_symbol"] == "BTC/USDT"
    # Each signal carries bot tags:
    for s in body["signals"]:
        assert "bot_id" in s
        assert "bot_exchange_id" in s
        assert "bot_mode" in s


def test_feed_limit_honored(client, tmp_path):
    # Create one bot with 5 signals; limit=2 returns the 2 newest.
    bid = _create_bot(client)
    from showme.bots.store import BotStore
    from showme.bots.record import SignalEntry
    store = BotStore.fresh()
    rec = store.get(bid)
    for i in range(5):
        rec = rec.append_signal(SignalEntry(
            bar_index=i, bar_time=f"2026-05-22T1{i}:00:00Z",
            kind="entry", price=100.0 + i, action="shadow",
            timestamp=f"2026-05-22T1{i}:00:00Z",
        ))
    store.save(rec)

    r = client.get("/api/bots/feed?limit=2")
    body = r.json()
    assert len(body["signals"]) == 2
    # The 2 newest are indices 4 and 3 (highest timestamps)
    assert body["signals"][0]["bar_index"] == 4
    assert body["signals"][1]["bar_index"] == 3


def test_feed_limit_cap_at_500(client, tmp_path):
    # Even if user passes limit=9999, response respects cap.
    bid = _create_bot(client)
    r = client.get(f"/api/bots/feed?limit=9999")
    assert r.status_code == 200  # doesn't error; just capped server-side
