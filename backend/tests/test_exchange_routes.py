"""FastAPI route tests for /api/exchange/*.

The store is forced to the memory backend via env, and the catalog is
patched onto the factory so we don't depend on ccxt's full registry."""
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
    # Reset factory dynamic state between tests:
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_catalog_returns_list(client: TestClient) -> None:
    r = client.get("/api/exchange/catalog")
    assert r.status_code == 200
    body = r.json()
    assert isinstance(body, list)
    assert {e["id"] for e in body} >= {"binance"}


def test_list_credentials_starts_empty(client: TestClient) -> None:
    r = client.get("/api/exchange/credentials")
    assert r.status_code == 200
    assert r.json() == {"records": []}


def test_create_credential_persists_and_registers_broker(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance",
        "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"],
        "skip_test": True,
    })
    assert r.status_code == 200, r.text
    rec = r.json()
    assert rec["exchange_id"] == "binance"
    assert rec["permissions"] == ["read"]
    # No secret leaks in body:
    assert "api_key" not in r.text and "api_secret" not in r.text
    # Broker is now in the registry:
    list_r = client.get(f"/api/broker/positions?name=binance:{rec['id']}")
    assert list_r.status_code == 200


def test_create_credential_validates_against_catalog(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "not-an-exchange",
        "account_label": "x",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"],
        "skip_test": True,
    })
    assert r.status_code == 400


def test_create_credential_requires_all_fields_from_catalog(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance",
        "account_label": "main",
        "secrets": {"api_key": "k"},  # missing api_secret
        "permissions": ["read"],
        "skip_test": True,
    })
    assert r.status_code == 400
    assert "api_secret" in r.json()["detail"]


def test_delete_credential_removes_broker(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]
    d = client.delete(f"/api/exchange/credentials/{rid}")
    assert d.status_code == 200
    list_r = client.get(f"/api/broker/positions?name=binance:{rid}")
    assert list_r.status_code == 404


def test_test_credential_calls_account(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]
    t = client.post(f"/api/exchange/credentials/{rid}/test")
    assert t.status_code == 200
    body = t.json()
    assert body["ok"] is True
    assert body["account"]["equity"] == 10


def test_successful_test_records_last_verified(client: TestClient) -> None:
    """B1 — a successful POST .../test stamps last_verified, returns it, and
    it then appears in the list metadata."""
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]
    # Before any test, last_verified is None in the listing.
    listed_before = client.get("/api/exchange/credentials").json()["records"]
    rec_before = next(x for x in listed_before if x["id"] == rid)
    assert rec_before["last_verified"] is None

    t = client.post(f"/api/exchange/credentials/{rid}/test")
    assert t.status_code == 200
    body = t.json()
    assert body["ok"] is True
    assert body["last_verified"] is not None
    # No secret leaks in the test response.
    assert "api_key" not in t.text and "api_secret" not in t.text

    # And the new timestamp is reflected in the list metadata.
    listed_after = client.get("/api/exchange/credentials").json()["records"]
    rec_after = next(x for x in listed_after if x["id"] == rid)
    assert rec_after["last_verified"] == body["last_verified"]


def test_failed_test_leaves_last_verified_unchanged(
    client: TestClient, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """B1 — a failed connection test must NOT update last_verified."""
    import showme.brokers as brokers_mod

    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]

    class _BoomBroker:
        async def account(self):
            raise RuntimeError("auth rejected")

    # The route does `from showme.brokers import ... get_broker` at call time,
    # so patch the name on the package the route imports from.
    monkeypatch.setattr(brokers_mod, "get_broker", lambda *_a, **_k: _BoomBroker())
    t = client.post(f"/api/exchange/credentials/{rid}/test")
    assert t.status_code == 200
    body = t.json()
    assert body["ok"] is False
    assert "last_verified" not in body

    # last_verified stays None after the failed test.
    listed = client.get("/api/exchange/credentials").json()["records"]
    rec = next(x for x in listed if x["id"] == rid)
    assert rec["last_verified"] is None


def test_list_credentials_exposes_last_verified_metadata(client: TestClient) -> None:
    """B1 — last_verified is part of the metadata-only to_dict() shape (and is
    never accompanied by a secret)."""
    client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    listed = client.get("/api/exchange/credentials")
    assert "last_verified" in listed.json()["records"][0]
    assert "api_key" not in listed.text and "api_secret" not in listed.text


def test_patch_permissions_requires_re_typed_label(client: TestClient) -> None:
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "main",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]
    # Without confirm_account_label → 400
    bad = client.patch(f"/api/exchange/credentials/{rid}", json={
        "permissions": ["read", "trade"],
    })
    assert bad.status_code == 400
    # Wrong confirm → 400
    wrong = client.patch(f"/api/exchange/credentials/{rid}", json={
        "permissions": ["read", "trade"],
        "confirm_account_label": "wrong",
    })
    assert wrong.status_code == 400
    # Correct confirm → 200
    good = client.patch(f"/api/exchange/credentials/{rid}", json={
        "permissions": ["read", "trade"],
        "confirm_account_label": "main",
    })
    assert good.status_code == 200
    assert good.json()["permissions"] == ["read", "trade"]


def test_patch_ignores_legacy_account_label_field(client: TestClient) -> None:
    """The CredentialPatch shape no longer accepts account_label; sending
    one is silently ignored. The stored label is unchanged."""
    r = client.post("/api/exchange/credentials", json={
        "exchange_id": "binance", "account_label": "original-label",
        "secrets": {"api_key": "k", "api_secret": "s"},
        "permissions": ["read"], "skip_test": True,
    })
    rid = r.json()["id"]
    patched = client.patch(f"/api/exchange/credentials/{rid}", json={
        "account_label": "renamed",  # unknown field — Pydantic ignores
        "permissions": ["read"],
    })
    assert patched.status_code == 200
    # Label is unchanged:
    listed = client.get("/api/exchange/credentials").json()
    rec = next(r for r in listed["records"] if r["id"] == rid)
    assert rec["account_label"] == "original-label"
