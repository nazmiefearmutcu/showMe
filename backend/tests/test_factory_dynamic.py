"""Dynamic credential→broker registration via factory."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from showme.brokers import factory as factory_mod
from showme.brokers.catalog.loader import load_catalog
from showme.brokers.credential_store import CredentialStore


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


@pytest.fixture(autouse=True)
def _isolate_factory_registry(monkeypatch: pytest.MonkeyPatch):
    """Snapshot and restore the factory's mutable module state between
    tests so a leaked dynamic broker can't bleed into the next test (or
    the rest of the suite via warning leaks)."""
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    yield
    factory_mod._REGISTRY.clear()
    factory_mod._REGISTRY.update(snap_reg)
    factory_mod._DYNAMIC.clear()
    factory_mod._DYNAMIC.update(snap_dyn)
    factory_mod._LIVE.clear()
    factory_mod._LIVE.update(snap_live)


@pytest.fixture
def env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    return tmp_path


def _patch_factory_catalog(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    yml = tmp_path / "ex.yml"
    yml.write_text(YAML)
    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))


def _fake_ccxt() -> SimpleNamespace:
    class _Ex:
        def __init__(self, config=None, **_kw):
            self.fetch_balance = AsyncMock(return_value={"total": {"USDT": 10}, "free": {"USDT": 10}})
            self.close = AsyncMock()
    return SimpleNamespace(async_support=SimpleNamespace(binance=_Ex))


def test_register_credential_makes_broker_lookup(monkeypatch, env):
    _patch_factory_catalog(monkeypatch, env)
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())
    store = CredentialStore.fresh()
    rec = store.add(
        exchange_id="binance", account_label="main",
        secrets={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    factory_mod.register_credential(rec, {"api_key": "k", "api_secret": "s"})
    name = f"binance:{rec.id}"
    assert name in factory_mod.list_brokers()
    broker = factory_mod.get_broker(name)
    assert broker.name == "ccxt:binance"


@pytest.mark.asyncio
async def test_replay_stored_credentials_registers_each(monkeypatch, env):
    _patch_factory_catalog(monkeypatch, env)
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())
    store = CredentialStore.fresh()
    a = store.add(exchange_id="binance", account_label="main",
                  secrets={"api_key": "k1", "api_secret": "s1"}, permissions=("read",))
    b = store.add(exchange_id="binance", account_label="tax",
                  secrets={"api_key": "k2", "api_secret": "s2"}, permissions=("read", "trade"))
    factory_mod.replay_stored_credentials(store)
    names = factory_mod.list_brokers()
    assert f"binance:{a.id}" in names
    assert f"binance:{b.id}" in names


def test_unregister_credential_removes_broker(monkeypatch, env):
    _patch_factory_catalog(monkeypatch, env)
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())
    store = CredentialStore.fresh()
    rec = store.add(exchange_id="binance", account_label="main",
                    secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",))
    factory_mod.register_credential(rec, {"api_key": "k", "api_secret": "s"})
    name = f"binance:{rec.id}"
    assert name in factory_mod.list_brokers()
    factory_mod.unregister_credential(rec.id)
    assert name not in factory_mod.list_brokers()
