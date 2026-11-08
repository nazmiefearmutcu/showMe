"""SEC-4 — POST /api/broker/positions/{symbol}/close submits a live exit order.

Bug: the close route called ``broker.close_position(symbol, quantity)`` with
no typed-confirmation gate, while ``POST /api/broker/orders`` requires one.
With ``quantity`` omitted the whole position is closed, so a bare request
could liquidate a live position.

Fix: the close route applies the same typed-confirmation check as the order
route (``confirmation_token`` or the legacy ``confirm_account_label``) before
the broker is asked to close anything.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from showme.server import build_app


class _FakeOrder:
    def to_dict(self) -> dict:
        return {"id": "close-1", "status": "filled"}


class _RecordingBroker:
    name = "paper"

    def __init__(self) -> None:
        self.calls: list[tuple[str, float | None]] = []

    async def close_position(self, symbol: str, *, quantity=None):
        self.calls.append((symbol, quantity))
        return _FakeOrder()


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_BROKER", "paper")
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


@pytest.fixture
def broker(monkeypatch):
    fake = _RecordingBroker()
    import showme.brokers as brokers_mod

    monkeypatch.setattr(brokers_mod, "get_broker", lambda name=None: fake)
    return fake


def test_close_rejects_when_confirmation_missing(client, broker):
    r = client.post("/api/broker/positions/AAPL/close", json={})
    assert r.status_code == 400, r.text
    assert "confirmation_token required" in r.json()["detail"]
    # The broker must never be asked to close anything without the gate.
    assert broker.calls == []


def test_close_rejects_wrong_confirmation(client, broker):
    r = client.post(
        "/api/broker/positions/AAPL/close",
        json={"confirmation_token": "not-paper"},
    )
    assert r.status_code == 400, r.text
    assert "mismatch" in r.json()["detail"]
    assert broker.calls == []


def test_close_accepts_matching_confirmation(client, broker):
    r = client.post(
        "/api/broker/positions/AAPL/close",
        json={"confirmation_token": "paper"},
    )
    assert r.status_code == 200, r.text
    assert broker.calls == [("AAPL", None)]
    assert r.json()["order"]["id"] == "close-1"


def test_close_accepts_legacy_confirmation_alias(client, broker):
    r = client.post(
        "/api/broker/positions/AAPL/close",
        json={"quantity": 2, "confirm_account_label": "paper"},
    )
    assert r.status_code == 200, r.text
    assert broker.calls == [("AAPL", 2.0)]
