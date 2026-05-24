"""A02-2026-05-24 — broker safety regression.

Bug: ``POST /api/broker/orders`` accepted ``{symbol, qty, side}`` directly
without any typed-confirmation token, even though the UI ``OrderTicket``
enforces one. The moment a live Binance/Alpaca credential lands, a
curl-quality client could drop a real order with no friction.

Fix: ``OrderRequest.resolved_confirmation()`` returns the
client-supplied confirmation; the route compares it against the
broker's identity label (broker name for ``paper``, credential
``account_label`` for ``{exchange}:{credential_id}``) and 400s on
absence/mismatch. The same gate applies to paper so the UI contract
stays uniform — wiring a live credential becomes a zero-line UI
change.
"""
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
    monkeypatch.setenv("SHOWME_BROKER", "paper")
    # Reset the broker factory so each test sees an empty registry
    # plus the default ``paper`` registration.
    from showme.brokers import factory as factory_mod
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def _seed_credential() -> str:
    """Seed a credential so dynamic brokers register through the
    factory. Returns the credential id."""
    from showme.brokers import CredentialStore, factory as factory_mod
    store = CredentialStore.fresh()
    rec = store.add(
        exchange_id="binance",
        account_label="trade-main",
        secrets={"apiKey": "k", "secret": "s"},
        permissions=("read", "trade"),
    )
    # Register a fake factory under the canonical name so
    # ``get_broker`` doesn't try to spin up a real ccxt client during
    # tests (which would need a live network).
    name = f"binance:{rec.id}"

    class _StubBroker:
        def __init__(self, label: str) -> None:
            self.name = label

        async def submit_order(self, **kwargs):
            class _Order:
                def to_dict(self_inner):
                    return {"id": "stub-1", "status": "FILLED", **kwargs}
            return _Order()

    factory_mod.register_broker(name, lambda label=name: _StubBroker(label))
    factory_mod._DYNAMIC[rec.id] = name
    return rec.id


# ── Missing token ──────────────────────────────────────────────────────


def test_paper_submit_rejects_when_token_missing(client):
    """No ``confirmation_token``/``confirm_account_label`` → 400. This is
    the headline curl-bypass case from the bug report."""
    r = client.post("/api/broker/orders", json={
        "symbol": "AAPL", "side": "buy", "quantity": 1,
        "notes": "last:200",
    })
    assert r.status_code == 400, r.text
    detail = r.json()["detail"]
    assert "confirmation_token required" in detail
    assert "paper" in detail


def test_paper_submit_rejects_empty_token(client):
    r = client.post("/api/broker/orders", json={
        "symbol": "AAPL", "side": "buy", "quantity": 1,
        "notes": "last:200", "confirmation_token": "   ",
    })
    assert r.status_code == 400, r.text
    assert "confirmation_token required" in r.json()["detail"]


# ── Mismatched token ───────────────────────────────────────────────────


def test_paper_submit_rejects_wrong_token(client):
    r = client.post("/api/broker/orders", json={
        "symbol": "AAPL", "side": "buy", "quantity": 1,
        "notes": "last:200", "confirmation_token": "not-paper",
    })
    assert r.status_code == 400, r.text
    assert "mismatch" in r.json()["detail"]


# ── Happy path — paper ─────────────────────────────────────────────────


def test_paper_submit_accepts_matching_token(client):
    r = client.post("/api/broker/orders", json={
        "symbol": "AAPL", "side": "buy", "quantity": 1,
        "notes": "last:200", "confirmation_token": "paper",
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["broker"] == "paper"
    # Paper broker's OrderStatus enum lowercases on serialize. We only
    # care that the order made it past the gate, not the exact case.
    assert str(body["order"]["status"]).upper() == "FILLED"


def test_paper_submit_accepts_legacy_alias(client):
    """Backwards-compat: callers may use ``confirm_account_label``
    (the field name the bots route already uses)."""
    r = client.post("/api/broker/orders", json={
        "symbol": "AAPL", "side": "buy", "quantity": 1,
        "notes": "last:200", "confirm_account_label": "paper",
    })
    assert r.status_code == 200, r.text


# ── Credential-backed broker ───────────────────────────────────────────


def test_dynamic_broker_uses_credential_account_label(client):
    cid = _seed_credential()
    broker_name = f"binance:{cid}"
    # Wrong label → 400.
    r = client.post("/api/broker/orders", json={
        "broker": broker_name,
        "symbol": "BTC/USDT", "side": "buy", "quantity": 0.001,
        "confirmation_token": "paper",
    })
    assert r.status_code == 400, r.text
    assert "mismatch" in r.json()["detail"]
    # Right label → 200.
    r2 = client.post("/api/broker/orders", json={
        "broker": broker_name,
        "symbol": "BTC/USDT", "side": "buy", "quantity": 0.001,
        "confirmation_token": "trade-main",
    })
    assert r2.status_code == 200, r2.text
    assert r2.json()["broker"] == broker_name


def test_dynamic_broker_rejects_when_credential_removed(client):
    """If the broker is registered but the credential vault no longer
    has the record (rare race during disconnect), the route 400s with
    a clear reason instead of silently letting the order through."""
    from showme.brokers import factory as factory_mod

    class _StubBroker:
        name = "binance:ghost-credential"

        async def submit_order(self, **kwargs):
            raise AssertionError("must not be called when token unresolved")

    factory_mod.register_broker(_StubBroker.name, lambda: _StubBroker())
    try:
        r = client.post("/api/broker/orders", json={
            "broker": _StubBroker.name,
            "symbol": "BTC/USDT", "side": "buy", "quantity": 0.001,
            "confirmation_token": "anything",
        })
        assert r.status_code == 400, r.text
        assert "no active account label" in r.json()["detail"]
    finally:
        factory_mod._REGISTRY.pop(_StubBroker.name, None)
        factory_mod._LIVE.pop(_StubBroker.name, None)
