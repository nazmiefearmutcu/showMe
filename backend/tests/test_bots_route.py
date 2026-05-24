"""FastAPI route tests for /api/bots/*.

Faz 5 — Stale test alignment. The original tests pinned the buggy
contract where ``POST /api/bots`` accepted placeholder
``strategy_id="s1"`` / ``credential_id="c1"`` strings. Faz 1-3 shipped
the S5 FK validation fix in ``server_routes/bots.py`` (now refuses any
non-existent FK with a 400). These tests are rewritten to seed real
fixtures so the happy-path is reachable again.
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
    # Reset factory module state
    from showme.brokers import factory as factory_mod
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    # Reset bot lifespan singleton
    import showme.bots.lifespan as lifespan
    lifespan._RUNNER = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def _seed_strategy(client) -> str:
    """Create a real strategy via the API and return its id."""
    r = client.post("/api/strategies", json=_STRATEGY_BODY)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_credential(read_only: bool = False) -> str:
    """Add a real credential directly to the vault. Returns the id."""
    from showme.brokers import CredentialStore
    store = CredentialStore.fresh()
    perms: tuple[str, ...] = ("read",) if read_only else ("read", "trade")
    rec = store.add(
        exchange_id="binance",
        account_label="main",
        secrets={"apiKey": "k", "secret": "s"},
        permissions=perms,
    )
    return rec.id


@pytest.fixture
def seeded(client):
    """Bundle of valid FKs for happy-path bot creation."""
    sid = _seed_strategy(client)
    cid = _seed_credential()
    return {
        "strategy_id": sid,
        "credential_id": cid,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "tick_interval_seconds": 900,
    }


def test_list_empty(client):
    r = client.get("/api/bots")
    assert r.status_code == 200
    assert r.json() == {"records": []}


def test_create_forces_shadow_and_disabled(client, seeded):
    body = dict(seeded, mode="live", enabled=True)  # client tries to skip safety
    r = client.post("/api/bots", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["mode"] == "shadow"  # forced
    assert j["enabled"] is False  # forced


def test_get_and_delete_round_trip(client, seeded):
    r = client.post("/api/bots", json=seeded)
    bid = r.json()["id"]
    g = client.get(f"/api/bots/{bid}")
    assert g.status_code == 200
    d = client.delete(f"/api/bots/{bid}")
    assert d.status_code == 200
    assert client.get(f"/api/bots/{bid}").status_code == 404


def test_put_preserves_signal_log(client, seeded):
    r = client.post("/api/bots", json=seeded)
    bid = r.json()["id"]
    p = client.put(f"/api/bots/{bid}", json=dict(seeded, symbol="ETH/USDT"))
    assert p.status_code == 200, p.text
    assert p.json()["symbol"] == "ETH/USDT"
    assert p.json()["signal_log"] == []


def test_put_live_mode_requires_credential_trade(client):
    """Live-mode PUT requires the credential to have 'trade' permission.
    Faz 5: seed a read-only credential so the route reaches the trade-perm
    check (used to reach it via the FK-less path with placeholder ``c1``)."""
    sid = _seed_strategy(client)
    cid_readonly = _seed_credential(read_only=True)
    body = {
        "strategy_id": sid,
        "credential_id": cid_readonly,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "tick_interval_seconds": 900,
    }
    r = client.post("/api/bots", json=body)
    assert r.status_code == 200, r.text
    bid = r.json()["id"]
    bad = client.put(f"/api/bots/{bid}", json={
        **body, "mode": "live", "confirm_account_label": "main",
    })
    assert bad.status_code == 400, bad.text
    assert "trade" in bad.json()["detail"]


def test_enable_disable_round_trip(client, seeded):
    # Register a (mock) broker under the seeded credential id so enable can
    # spawn a task. Bot enable doesn't go through the catalog factory path
    # but does need ``binance:<credential_id>`` resolvable.
    from showme.brokers import factory as factory_mod
    from unittest.mock import MagicMock, AsyncMock
    broker = MagicMock()
    broker.name = "ccxt:binance"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    cid = seeded["credential_id"]
    factory_mod._REGISTRY[f"binance:{cid}"] = lambda b=broker: b
    factory_mod._DYNAMIC[cid] = f"binance:{cid}"

    r = client.post("/api/bots", json=seeded)
    bid = r.json()["id"]
    e = client.post(f"/api/bots/{bid}/enable")
    assert e.status_code == 200, e.text
    assert e.json()["enabled"] is True
    d = client.post(f"/api/bots/{bid}/disable")
    assert d.status_code == 200
    assert d.json()["enabled"] is False


def test_signals_endpoint(client, seeded):
    r = client.post("/api/bots", json=seeded)
    bid = r.json()["id"]
    s = client.get(f"/api/bots/{bid}/signals")
    assert s.status_code == 200
    assert s.json()["signals"] == []
    assert s.json()["last_processed_event"] is None


def test_404_routes(client):
    assert client.get("/api/bots/missing").status_code == 404
    assert client.get("/api/bots/missing/signals").status_code == 404
    assert client.delete("/api/bots/missing").status_code == 404


# ── Agent 2 regression tests (BOT_AUDIT_REPORT.md) ──────────────────────


def test_put_strips_signal_log_injection(client, seeded):
    """C-API-3 / FIX_CONTRACT.md C8: PUT body MUST NOT accept ``signal_log``
    (or other runtime-state fields). Forged entries persist to disk and
    poison PnL / leaderboard otherwise.
    """
    r = client.post("/api/bots", json=seeded)
    bid = r.json()["id"]
    forged_log = [
        {
            "bar_index": i,
            "bar_time": f"2026-05-22T1{i}:00:00Z",
            "kind": "entry",
            "price": 99999.0,
            "action": "placed",
            "order_id": f"FORGED-{i}",
        }
        for i in range(50)
    ]
    p = client.put(
        f"/api/bots/{bid}",
        json={**seeded, "symbol": "ETH/USDT", "signal_log": forged_log},
    )
    assert p.status_code == 200, p.text
    body = p.json()
    # Server MUST have ignored the body's signal_log and preserved the
    # existing (empty in this case) runtime state.
    assert body["signal_log"] == []
    # Read back via GET to double-check disk state.
    g = client.get(f"/api/bots/{bid}").json()
    assert g["signal_log"] == []


def test_put_strips_other_runtime_state_fields(client, seeded):
    """C-API-3 — defense-in-depth for every field in _PUT_STRIPPED_FIELDS."""
    r = client.post("/api/bots", json=seeded)
    bid = r.json()["id"]
    forged_event = {
        "bar_index": 9, "bar_time": "2026-05-22T09:00:00Z",
        "kind": "entry", "price": 1.0, "action": "placed",
    }
    p = client.put(
        f"/api/bots/{bid}",
        json={
            **seeded,
            "symbol": "ETH/USDT",
            "enabled": True,                 # MUST be ignored — /enable owns this
            "last_processed_event": forged_event,
            "closed_trades_log": [{"foo": "bar"}],
            "created_at": "1970-01-01T00:00:00Z",
            "updated_at": "1970-01-01T00:00:00Z",
        },
    )
    assert p.status_code == 200, p.text
    body = p.json()
    assert body["enabled"] is False  # preserved from existing record
    assert body["last_processed_event"] is None
    assert body["created_at"] != "1970-01-01T00:00:00Z"


def test_negative_sizing_rejected_at_route(client):
    """C-API-1 — POST /api/strategies with negative ``sizing_value`` must 400."""
    body = {
        "name": "negative-sizing",
        "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
        "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
        "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
        "exit_logic": "any",
        "position": {"sizing_kind": "fixed_quote", "sizing_value": -100},
    }
    r = client.post("/api/strategies", json=body)
    assert r.status_code == 400, r.text
    assert "sizing_value" in r.json()["detail"]


def test_over_100_risk_pct_rejected(client):
    """C-API-1 — risk_pct sizing capped at 100 (else 2x+ over-leverage)."""
    body = {
        "name": "over-leveraged",
        "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
        "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
        "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
        "exit_logic": "any",
        "position": {"sizing_kind": "risk_pct", "sizing_value": 200.0},
    }
    r = client.post("/api/strategies", json=body)
    assert r.status_code == 400, r.text


def test_zero_sizing_rejected(client):
    """C-API-1 — sizing_value=0 must 400 (else qty=0 silent skip)."""
    body = {
        "name": "zero-sizing",
        "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
        "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
        "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
        "exit_logic": "any",
        "position": {"sizing_kind": "fixed_quote", "sizing_value": 0.0},
    }
    r = client.post("/api/strategies", json=body)
    assert r.status_code == 400, r.text
    assert "sizing_value" in r.json()["detail"]


def test_enable_requires_broker_registry(client, seeded):
    """H-API-1 — /enable refuses when no broker is registered for
    ``{exchange_id}:{credential_id}``. Without this guard the bot
    enables successfully but every tick fires 'broker unavailable'.
    """
    # Note: the ``seeded`` fixture creates a credential but does NOT
    # register a broker in the factory (skip_test path). The H-API-1 fix
    # MUST now block enable for this combination.
    r = client.post("/api/bots", json=seeded)
    bid = r.json()["id"]
    e = client.post(f"/api/bots/{bid}/enable")
    assert e.status_code == 400, e.text
    assert "broker not registered" in e.json()["detail"]


def test_list_bots_includes_signal_count(client, seeded):
    """H-SUP-2 — GET /api/bots includes ``signal_count`` per record so
    the supervisor UI can show accurate per-bot tallies."""
    r = client.post("/api/bots", json=seeded)
    bid = r.json()["id"]

    # Seed three signals on this bot.
    from showme.bots.store import BotStore
    from showme.bots.record import SignalEntry
    store = BotStore.fresh()
    rec = store.get(bid)
    for i in range(3):
        rec = rec.append_signal(SignalEntry(
            bar_index=i, bar_time=f"2026-05-22T1{i}:00:00Z", kind="entry",
            price=100.0 + i, action="shadow", timestamp=f"2026-05-22T1{i}:00:00Z",
        ))
    store.save(rec)

    lst = client.get("/api/bots").json()
    assert any(
        b.get("id") == bid and b.get("signal_count") == 3
        for b in lst["records"]
    )
