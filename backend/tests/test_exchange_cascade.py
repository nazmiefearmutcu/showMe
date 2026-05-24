"""FastAPI route tests for /api/exchange/credentials cascade behaviour.

Covers BOT_AUDIT_REPORT.md C-INT-1: credential DELETE used to orphan
bots that referenced the credential, leaving live asyncio tasks running
against a no-longer-registered broker. Faz-1 fix gates the destructive
op behind ``?force=true`` and adds a /dependents endpoint.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from showme.brokers import factory as factory_mod
from showme.brokers.catalog.loader import load_catalog
from showme.server import build_app


YAML = """
- id: binance
  display_name: Binance
  aliases: []
  asset_classes: [spot]
  regions: [global]
  adapter: ccxt
  ccxt_id: binance
  requires: [api_key, api_secret]
  optional: []
  capabilities: {fetch_balance: true, fetch_positions: true, fetch_open_orders: true, create_order: true, cancel_order: true}
"""


_STRATEGY_BODY = {
    "name": "RSI mean revert (cascade fixture)",
    "indicators": [{"alias": "rsi14", "id": "rsi", "params": {"period": 14}}],
    "entry_rules": [{"kind": "crosses_below", "left": "rsi14", "right": "literal:30"}],
    "exit_rules": [{"kind": "crosses_above", "left": "rsi14", "right": "literal:70"}],
    "exit_logic": "any",
}


def _fake_ccxt() -> SimpleNamespace:
    class _Ex:
        def __init__(self, config=None, **_kw):
            self.fetch_balance = AsyncMock(return_value={"total": {"USDT": 10}, "free": {"USDT": 10}})
            self.fetch_positions = AsyncMock(return_value=[])
            self.fetch_open_orders = AsyncMock(return_value=[])
            self.close = AsyncMock()
    return SimpleNamespace(async_support=SimpleNamespace(binance=_Ex))


@pytest.fixture
def client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    yml = tmp_path / "ex.yml"
    yml.write_text(YAML)
    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    import showme.bots.lifespan as lifespan
    lifespan._RUNNER = None
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def _seed_credential(client: TestClient) -> str:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance",
        "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read", "trade"],
        "skip_test": True,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_strategy(client: TestClient) -> str:
    r = client.post("/api/strategies", json=_STRATEGY_BODY)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def _seed_bot(client: TestClient, *, strategy_id: str, credential_id: str) -> str:
    r = client.post("/api/bots", json={
        "strategy_id": strategy_id,
        "credential_id": credential_id,
        "exchange_id": "binance",
        "symbol": "BTC/USDT",
        "timeframe": "1h",
        "tick_interval_seconds": 900,
    })
    assert r.status_code == 200, r.text
    return r.json()["id"]


# ── /dependents ─────────────────────────────────────────────────────────


def test_credential_dependents_empty(client: TestClient) -> None:
    cid = _seed_credential(client)
    r = client.get(f"/api/exchange/credentials/{cid}/dependents")
    assert r.status_code == 200
    assert r.json() == {
        "credential_id": cid,
        "bot_count": 0,
        "bot_ids": [],
        "bots": [],
    }


def test_credential_dependents_lists_referencing_bots(client: TestClient) -> None:
    """C-INT-1 / FIX_CONTRACT.md C9: /dependents drives the CONN confirm UI."""
    cid = _seed_credential(client)
    sid = _seed_strategy(client)
    b1 = _seed_bot(client, strategy_id=sid, credential_id=cid)
    b2 = _seed_bot(client, strategy_id=sid, credential_id=cid)

    r = client.get(f"/api/exchange/credentials/{cid}/dependents")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["credential_id"] == cid
    assert body["bot_count"] == 2
    assert set(body["bot_ids"]) == {b1, b2}
    # Per-bot detail blocks for UI display.
    bots = {b["id"]: b for b in body["bots"]}
    assert bots[b1]["symbol"] == "BTC/USDT"
    assert bots[b1]["mode"] == "shadow"


# ── cascade DELETE ─────────────────────────────────────────────────────


def test_delete_credential_returns_409_when_bots_reference(client: TestClient) -> None:
    """C-INT-1 — DELETE without force=true MUST 409, leaving the
    credential AND its referencing bots intact so the UI can prompt the
    user about cascade-disable."""
    cid = _seed_credential(client)
    sid = _seed_strategy(client)
    bid = _seed_bot(client, strategy_id=sid, credential_id=cid)

    d = client.delete(f"/api/exchange/credentials/{cid}")
    assert d.status_code == 409, d.text
    body = d.json()
    assert body["detail"]["error"] == "credential_has_bots"
    assert body["detail"]["bot_count"] == 1
    assert bid in body["detail"]["bot_ids"]
    # Credential survives the failed attempt.
    listed = client.get("/api/exchange/credentials").json()
    assert any(rec["id"] == cid for rec in listed["records"])


def test_delete_credential_force_cascade_disables_bots(client: TestClient) -> None:
    """C-INT-1 — force=true cascade-disables every referencing bot, THEN
    deletes the credential + unregisters the broker."""
    cid = _seed_credential(client)
    sid = _seed_strategy(client)
    bid = _seed_bot(client, strategy_id=sid, credential_id=cid)
    # Confirm the broker is registered before the destructive op.
    name = f"binance:{cid}"
    assert name in factory_mod._REGISTRY

    d = client.delete(f"/api/exchange/credentials/{cid}?force=true")
    assert d.status_code == 200, d.text
    body = d.json()
    assert body["ok"] is True
    assert body["bots_affected"] == 1
    assert any(c.get("bot_id") == bid for c in body["cascade"])
    # Credential removed.
    listed = client.get("/api/exchange/credentials").json()
    assert not any(rec["id"] == cid for rec in listed["records"])
    # Broker unregistered (no zombie tasks).
    assert name not in factory_mod._REGISTRY
    # Bot is now disabled but still on disk.
    bg = client.get(f"/api/bots/{bid}")
    assert bg.status_code == 200
    assert bg.json()["enabled"] is False


def test_delete_credential_no_dependents_passes_without_force(client: TestClient) -> None:
    """Sanity: no bots → DELETE succeeds without force=true."""
    cid = _seed_credential(client)
    d = client.delete(f"/api/exchange/credentials/{cid}")
    assert d.status_code == 200
    assert d.json()["ok"] is True
    assert d.json()["bots_affected"] == 0


def test_delete_credential_unknown_returns_404(client: TestClient) -> None:
    """Missing credential is still a 404 (not 409 — we don't leak the
    cascade-check semantics when the resource doesn't exist)."""
    d = client.delete("/api/exchange/credentials/does-not-exist")
    # No bots reference it, so the FK check passes; then the store
    # delete returns False → 404.
    assert d.status_code == 404
