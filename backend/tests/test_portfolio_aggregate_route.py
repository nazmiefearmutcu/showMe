"""FastAPI route tests for /api/portfolio/aggregate."""
from __future__ import annotations


import pytest
from fastapi.testclient import TestClient

from showme.brokers import factory as factory_mod
from showme.brokers.catalog.loader import load_catalog
from showme.server import build_app
from showme import portfolio_aggregate as pa


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


class _FakeBroker:
    name = "ccxt:binance"
    def __init__(self, equity=100):
        self._equity = equity
    async def account(self):
        return {"cash": self._equity, "equity": self._equity,
                "buying_power": self._equity, "currency": "USDT", "raw": {}}
    async def list_positions(self):
        return []
    async def list_orders(self, *, status="open", limit=100):
        return []
    async def aclose(self):
        pass


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    monkeypatch.setenv("SHOWME_AUTH_TOKEN", "test-token")
    yml = tmp_path / "ex.yml"
    yml.write_text(YAML)
    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))
    pa._CACHE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    app = build_app(engine_root=None)
    return TestClient(app, headers={"X-ShowMe-Token": "test-token"})


def test_aggregate_empty(client):
    r = client.get("/api/portfolio/aggregate")
    assert r.status_code == 200
    body = r.json()
    assert body["groups"] == []
    assert body["totals"]["equity_by_currency"] == {}


def test_aggregate_one_group(client):
    factory_mod._REGISTRY["binance:abc"] = lambda: _FakeBroker(equity=42)
    factory_mod._DYNAMIC["abc"] = "binance:abc"
    r = client.get("/api/portfolio/aggregate")
    assert r.status_code == 200
    body = r.json()
    assert len(body["groups"]) == 1
    g = body["groups"][0]
    assert g["credential_id"] == "abc"
    assert g["account"]["equity"] == 42


def test_aggregate_credential_filter(client):
    factory_mod._REGISTRY["binance:a"] = lambda: _FakeBroker(equity=1)
    factory_mod._REGISTRY["binance:b"] = lambda: _FakeBroker(equity=2)
    factory_mod._DYNAMIC["a"] = "binance:a"
    factory_mod._DYNAMIC["b"] = "binance:b"
    r = client.get("/api/portfolio/aggregate?credential_ids=a")
    body = r.json()
    assert [g["credential_id"] for g in body["groups"]] == ["a"]


def test_aggregate_include_orders_flag(client):
    factory_mod._REGISTRY["binance:abc"] = lambda: _FakeBroker(equity=1)
    factory_mod._DYNAMIC["abc"] = "binance:abc"
    r = client.get("/api/portfolio/aggregate?include_orders=true")
    body = r.json()
    assert body["groups"][0]["orders"] == []
