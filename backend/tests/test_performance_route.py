"""Performance routes tests.

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
    # Reset factory module state.
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
        "symbol": symbol, "timeframe": "1h", "tick_interval_seconds": 60,
    })
    assert r.status_code == 200, r.text
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


def _push_signal_with_source(bot_id, *, equity_source: str):
    """Seed a single signal_log entry carrying an explicit equity_source so the
    detail route's provenance derivation (B2) can be exercised."""
    from showme.bots.store import BotStore
    from showme.bots.record import SignalEntry
    store = BotStore.fresh()
    rec = store.get(bot_id)
    rec = rec.append_signal(SignalEntry(
        bar_index=0, bar_time="2026-05-22T10:00:00Z", kind="entry", price=100.0,
        action="placed", timestamp="2026-05-22T10:00:00Z",
        equity_source=equity_source,
    ))
    store.save(rec)


def test_leaderboard_empty(client):
    r = client.get("/api/bots/performance")
    assert r.status_code == 200
    assert r.json()["records"] == []


def test_leaderboard_with_two_bots(client, seeded):
    a = _create_bot(client, seeded, "BTC/USDT")
    b = _create_bot(client, seeded, "ETH/USDT")
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


def test_bot_performance_detail(client, seeded):
    bid = _create_bot(client, seeded)
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


# ─── B1 — freshness stamp on both perf routes ────────────────────────────
def _assert_iso(value) -> None:
    """A non-empty, parseable ISO-8601 string. No wall-clock value assertion
    (deterministic across machines)."""
    from datetime import datetime
    assert isinstance(value, str) and value, value
    # datetime.fromisoformat parses the `datetime.now(...).isoformat()` output.
    datetime.fromisoformat(value)


def test_leaderboard_includes_generated_at(client, seeded):
    _create_bot(client, seeded, "BTC/USDT")
    r = client.get("/api/bots/performance")
    assert r.status_code == 200, r.text
    _assert_iso(r.json()["generated_at"])


def test_leaderboard_generated_at_present_when_empty(client):
    r = client.get("/api/bots/performance")
    assert r.status_code == 200
    assert r.json()["records"] == []
    _assert_iso(r.json()["generated_at"])


def test_detail_includes_generated_at(client, seeded):
    bid = _create_bot(client, seeded)
    r = client.get(f"/api/bots/{bid}/performance")
    assert r.status_code == 200, r.text
    _assert_iso(r.json()["generated_at"])


# ─── B2 — honest equity provenance on the detail route ───────────────────
def test_detail_starting_equity_is_10000(client, seeded):
    bid = _create_bot(client, seeded)
    r = client.get(f"/api/bots/{bid}/performance")
    assert r.status_code == 200, r.text
    assert r.json()["starting_equity"] == 10000


def test_detail_equity_source_none_when_no_signal_source(client, seeded):
    bid = _create_bot(client, seeded)
    # No signal carries an equity_source (shadow bot / no live sizing).
    r = client.get(f"/api/bots/{bid}/performance")
    assert r.status_code == 200, r.text
    assert r.json()["equity_source"] is None


def test_detail_equity_source_fallback_10k(client, seeded):
    bid = _create_bot(client, seeded)
    _push_signal_with_source(bid, equity_source="fallback_10k")
    r = client.get(f"/api/bots/{bid}/performance")
    assert r.status_code == 200, r.text
    assert r.json()["equity_source"] == "fallback_10k"


def test_detail_equity_source_broker(client, seeded):
    bid = _create_bot(client, seeded)
    _push_signal_with_source(bid, equity_source="broker")
    r = client.get(f"/api/bots/{bid}/performance")
    assert r.status_code == 200, r.text
    assert r.json()["equity_source"] == "broker"
