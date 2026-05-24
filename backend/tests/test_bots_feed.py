"""GET /api/bots/feed aggregate signal feed tests.

Faz 5 — Stale test alignment. Original tests pinned placeholder
``strategy_id="s1"`` / ``credential_id="c1"`` that no longer pass S5
FK validation. Now we seed a real strategy + credential per fixture.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


_STRATEGY_BODY = {
    "name": "RSI mean revert (test fixture)",
    "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
    "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
    "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
    "exit_logic": "any",
}


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    # Reset factory module state — other test modules may have populated it.
    from showme.brokers import factory as factory_mod
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    import showme.bots.lifespan as lifespan
    lifespan._RUNNER = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def _seed_strategy(client) -> str:
    r = client.post("/api/strategies", json=_STRATEGY_BODY)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_credential() -> str:
    from showme.brokers import CredentialStore
    store = CredentialStore.fresh()
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"apiKey": "k", "secret": "s"},
        permissions=("read", "trade"),
    )
    return rec.id


@pytest.fixture
def seeded(client):
    """Shared FK fixture for bot creation in this module."""
    return {
        "strategy_id": _seed_strategy(client),
        "credential_id": _seed_credential(),
        "exchange_id": "binance",
    }


def _create_bot(client, seeded, symbol="BTC/USDT"):
    r = client.post("/api/bots", json={
        **seeded,
        "symbol": symbol, "timeframe": "1h", "tick_interval_seconds": 900,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_feed_empty(client):
    r = client.get("/api/bots/feed")
    assert r.status_code == 200
    body = r.json()
    assert body["signals"] == []
    assert "generated_at" in body


def test_feed_aggregates_across_bots(client, seeded, tmp_path):
    # Create two bots, manually push signals to their stores.
    a_id = _create_bot(client, seeded, symbol="BTC/USDT")
    b_id = _create_bot(client, seeded, symbol="ETH/USDT")

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


def test_feed_limit_honored(client, seeded, tmp_path):
    # Create one bot with 5 signals; limit=2 returns the 2 newest.
    bid = _create_bot(client, seeded)
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


def test_feed_limit_above_cap_returns_422(client, seeded, tmp_path):
    """H-API-4 — ``limit>500`` is now rejected with 422 (FastAPI Query
    bound) instead of silently capped.

    Previous behavior silently returned 200 with up to 500 entries; that
    made it easy for a client to think it was hitting the real cap.
    """
    _create_bot(client, seeded)
    r = client.get("/api/bots/feed?limit=9999")
    assert r.status_code == 422


# ── Agent 2 regression tests (BOT_AUDIT_REPORT.md H-API-4 + H-SUP-2) ────


def test_limit_negative_returns_422(client, seeded):
    """H-API-4 — ``limit=-1`` was silently 200 OK with empty body. Now 422."""
    _create_bot(client, seeded)
    r = client.get("/api/bots/feed?limit=-1")
    assert r.status_code == 422


def test_limit_zero_returns_422(client, seeded):
    """H-API-4 — ``limit=0`` is also no longer a stealth 200."""
    _create_bot(client, seeded)
    r = client.get("/api/bots/feed?limit=0")
    assert r.status_code == 422


def test_per_bot_signal_count_exposed_in_feed(client, seeded):
    """H-SUP-2 — ``per_bot_signal_count`` is the un-truncated tally so
    the supervisor UI can stop deriving counts from the windowed list.
    """
    bid = _create_bot(client, seeded)
    from showme.bots.store import BotStore
    from showme.bots.record import SignalEntry
    store = BotStore.fresh()
    rec = store.get(bid)
    for i in range(7):
        rec = rec.append_signal(SignalEntry(
            bar_index=i, bar_time=f"2026-05-22T1{i}:00:00Z", kind="entry",
            price=100.0 + i, action="shadow", timestamp=f"2026-05-22T1{i}:00:00Z",
        ))
    store.save(rec)
    r = client.get("/api/bots/feed?limit=3")
    body = r.json()
    # Even though the feed is windowed to 3, the per-bot map keeps the truth.
    assert body["per_bot_signal_count"][bid] == 7
    assert len(body["signals"]) == 3
