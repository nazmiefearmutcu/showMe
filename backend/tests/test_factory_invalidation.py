"""Factory invalidation hooks — fire when a credential is unregistered."""
from __future__ import annotations

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
def _isolate_factory(monkeypatch, tmp_path):
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    snap_hooks = list(factory_mod._INVALIDATION_HOOKS)
    yield
    factory_mod._REGISTRY.clear()
    factory_mod._REGISTRY.update(snap_reg)
    factory_mod._DYNAMIC.clear()
    factory_mod._DYNAMIC.update(snap_dyn)
    factory_mod._LIVE.clear()
    factory_mod._LIVE.update(snap_live)
    factory_mod._INVALIDATION_HOOKS[:] = snap_hooks


def _fake_ccxt() -> SimpleNamespace:
    class _Ex:
        def __init__(self, config=None, **_kw):
            self.fetch_balance = AsyncMock(return_value={"total": {"USDT": 10}, "free": {"USDT": 10}})
            self.close = AsyncMock()
    return SimpleNamespace(async_support=SimpleNamespace(binance=_Ex))


def _setup(monkeypatch, tmp_path):
    monkeypatch.setenv("SHOWME_CREDENTIAL_BACKEND", "memory")
    monkeypatch.setenv("SHOWME_HOME", str(tmp_path))
    yml = tmp_path / "ex.yml"
    yml.write_text(YAML)
    monkeypatch.setattr(factory_mod, "_CATALOG", load_catalog(yml))
    monkeypatch.setattr(factory_mod, "_ccxt_module", _fake_ccxt())


def test_invalidation_hook_fires_on_unregister(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    fired: list[str] = []
    factory_mod._INVALIDATION_HOOKS.append(lambda cid: fired.append(cid))
    store = CredentialStore.fresh()
    rec = store.add(exchange_id="binance", account_label="main",
                    secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",))
    factory_mod.register_credential(rec, {"api_key": "k", "api_secret": "s"})
    factory_mod.unregister_credential(rec.id)
    assert fired == [rec.id]


def test_hook_exception_does_not_block_unregister(monkeypatch, tmp_path):
    _setup(monkeypatch, tmp_path)
    factory_mod._INVALIDATION_HOOKS.append(lambda cid: (_ for _ in ()).throw(RuntimeError("boom")))
    store = CredentialStore.fresh()
    rec = store.add(exchange_id="binance", account_label="main",
                    secrets={"api_key": "k", "api_secret": "s"}, permissions=("read",))
    factory_mod.register_credential(rec, {"api_key": "k", "api_secret": "s"})
    # A throwing hook must NOT prevent the unregister itself.
    assert factory_mod.unregister_credential(rec.id) is True
    assert f"binance:{rec.id}" not in factory_mod.list_brokers()
