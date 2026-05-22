"""FastAPI route tests for /api/bots/*."""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


_BOT_BODY = {
    "strategy_id": "s1",
    "credential_id": "c1",
    "exchange_id": "binance",
    "symbol": "BTC/USDT",
    "timeframe": "1h",
    "tick_interval_seconds": 60,
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


def test_list_empty(client):
    r = client.get("/api/bots")
    assert r.status_code == 200
    assert r.json() == {"records": []}


def test_create_forces_shadow_and_disabled(client):
    body = dict(_BOT_BODY, mode="live", enabled=True)  # client tries to skip safety
    r = client.post("/api/bots", json=body)
    assert r.status_code == 200, r.text
    j = r.json()
    assert j["mode"] == "shadow"  # forced
    assert j["enabled"] is False  # forced


def test_get_and_delete_round_trip(client):
    r = client.post("/api/bots", json=_BOT_BODY)
    bid = r.json()["id"]
    g = client.get(f"/api/bots/{bid}")
    assert g.status_code == 200
    d = client.delete(f"/api/bots/{bid}")
    assert d.status_code == 200
    assert client.get(f"/api/bots/{bid}").status_code == 404


def test_put_preserves_signal_log(client):
    r = client.post("/api/bots", json=_BOT_BODY)
    bid = r.json()["id"]
    p = client.put(f"/api/bots/{bid}", json=dict(_BOT_BODY, symbol="ETH/USDT"))
    assert p.status_code == 200, p.text
    assert p.json()["symbol"] == "ETH/USDT"
    assert p.json()["signal_log"] == []


def test_put_live_mode_requires_credential_trade(client, monkeypatch):
    r = client.post("/api/bots", json=_BOT_BODY)
    bid = r.json()["id"]
    # No registered credential at all → permission lookup fails open=False.
    bad = client.put(f"/api/bots/{bid}", json={
        **_BOT_BODY, "mode": "live", "confirm_account_label": "main",
    })
    assert bad.status_code == 400
    assert "trade" in bad.json()["detail"]


def test_enable_disable_round_trip(client):
    # Create a bot pointing to a (mock) broker we register manually so enable can spawn a task.
    from showme.brokers import factory as factory_mod
    from unittest.mock import MagicMock, AsyncMock
    broker = MagicMock()
    broker.name = "ccxt:binance"
    broker._ex = MagicMock()
    broker._ex.fetch_ohlcv = AsyncMock(return_value=[])
    factory_mod._REGISTRY["binance:c1"] = lambda b=broker: b
    factory_mod._DYNAMIC["c1"] = "binance:c1"

    r = client.post("/api/bots", json=_BOT_BODY)
    bid = r.json()["id"]
    e = client.post(f"/api/bots/{bid}/enable")
    assert e.status_code == 200, e.text
    assert e.json()["enabled"] is True
    d = client.post(f"/api/bots/{bid}/disable")
    assert d.status_code == 200
    assert d.json()["enabled"] is False


def test_signals_endpoint(client):
    r = client.post("/api/bots", json=_BOT_BODY)
    bid = r.json()["id"]
    s = client.get(f"/api/bots/{bid}/signals")
    assert s.status_code == 200
    assert s.json()["signals"] == []
    assert s.json()["last_processed_event"] is None


def test_404_routes(client):
    assert client.get("/api/bots/missing").status_code == 404
    assert client.get("/api/bots/missing/signals").status_code == 404
    assert client.delete("/api/bots/missing").status_code == 404
