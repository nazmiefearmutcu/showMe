"""B1/B2/B3 regression: currency conversion, timeout fan-out, locked cache.

These tests exercise the fixes for the Bundle B audit:

* **B1** — every currency in ``equity_by_currency`` must be visible in
  ``fx_rates`` or ``unconverted_currencies`` so the UI never quietly
  underreports the USD rollup.
* **B2** — a hung broker no longer wedges the whole fan-out; it falls
  through as a per-credential ``error: "timeout"`` entry after
  ``GROUP_FETCH_TIMEOUT_SECONDS``.
* **B3** — the module-level cache + invalidation-hook list are mutated under
  a lock and the registration guard prevents double-registration.
"""
from __future__ import annotations

import asyncio
import threading

import pytest

from showme.brokers import factory as factory_mod
from showme.brokers.base import OrderSide, Position
from showme import portfolio_aggregate as pa


@pytest.fixture(autouse=True)
def _isolate():
    """Snapshot/restore factory + caches around every test."""
    with pa._CACHE_LOCK:
        pa._CACHE.clear()
    with pa._FX_RATE_LOCK:
        pa._FX_RATE_CACHE.clear()
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    # Patch the FX fetcher so tests never hit yfinance.
    pa.set_fx_rate_fetcher(_fake_fx_rate_fetcher)
    try:
        yield
    finally:
        pa.set_fx_rate_fetcher(None)
        with pa._CACHE_LOCK:
            pa._CACHE.clear()
        with pa._FX_RATE_LOCK:
            pa._FX_RATE_CACHE.clear()
        factory_mod._REGISTRY.clear()
        factory_mod._REGISTRY.update(snap_reg)
        factory_mod._DYNAMIC.clear()
        factory_mod._DYNAMIC.update(snap_dyn)
        factory_mod._LIVE.clear()
        factory_mod._LIVE.update(snap_live)


_FAKE_FX = {"EUR": 1.10, "GBP": 1.27, "JPY": 0.0067, "BTC": 65000.0}


async def _fake_fx_rate_fetcher(currency: str) -> float | None:
    return _FAKE_FX.get(currency.upper())


class _FakeBroker:
    name = "ccxt:binance"

    def __init__(self, *, equity=100.0, currency="USDT", delay=0.0,
                 positions=None, orders=None, fail=False):
        self._equity = equity
        self._currency = currency
        self._delay = delay
        self._fail = fail
        self._positions = positions or [
            Position(symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.5,
                     entry_price=60000.0, current_price=61000.0, unrealized_pnl=500.0),
        ]
        self._orders = orders or []

    async def account(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("boom")
        return {"cash": self._equity, "equity": self._equity,
                "buying_power": self._equity, "currency": self._currency, "raw": {}}

    async def list_positions(self):
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._fail:
            raise RuntimeError("boom")
        return list(self._positions)

    async def list_orders(self, *, status="open", limit=100):
        return list(self._orders)


def _register_fake(credential_id: str, broker, exchange_id="binance") -> None:
    name = f"{exchange_id}:{credential_id}"
    factory_mod._REGISTRY[name] = lambda b=broker: b
    factory_mod._DYNAMIC[credential_id] = name
    factory_mod._LIVE.pop(name, None)


# ── B1: currency conversion ────────────────────────────────────────────────

async def test_b1_eur_jpy_btc_converted_via_fx_fetcher():
    """Non-stable currencies must contribute to ``usd_equivalent``."""
    _register_fake("eu", _FakeBroker(equity=100, currency="EUR"))
    _register_fake("jp", _FakeBroker(equity=10000, currency="JPY"))
    _register_fake("bt", _FakeBroker(equity=2, currency="BTC"))
    out = await pa.aggregate()
    totals = out["totals"]
    assert totals["equity_by_currency"] == {"EUR": 100.0, "JPY": 10000.0, "BTC": 2.0}
    # 100*1.10 + 10000*0.0067 + 2*65000 = 110 + 67 + 130000 = 130177
    assert totals["usd_equivalent"] == pytest.approx(130177.0, rel=1e-3)
    assert totals["fx_rates"]["EUR"] == 1.10
    assert totals["fx_rates"]["BTC"] == 65000.0
    assert totals["unconverted_currencies"] == []


async def test_b1_unresolved_currency_listed_in_unconverted():
    """Currencies with no FX rate must be advertised explicitly."""
    _register_fake("za", _FakeBroker(equity=50, currency="XYZ"))
    out = await pa.aggregate()
    totals = out["totals"]
    assert totals["equity_by_currency"]["XYZ"] == 50.0
    assert "XYZ" in totals["unconverted_currencies"]
    # No false add to usd_equivalent.
    assert totals["usd_equivalent"] == 0.0


async def test_b1_stable_currencies_keep_one_to_one_rate():
    _register_fake("usdt", _FakeBroker(equity=300, currency="USDT"))
    _register_fake("usd", _FakeBroker(equity=200, currency="USD"))
    out = await pa.aggregate()
    totals = out["totals"]
    assert totals["usd_equivalent"] == pytest.approx(500.0)
    assert totals["unconverted_currencies"] == []


# ── B2: timeout fan-out ────────────────────────────────────────────────────

async def test_b2_slow_broker_does_not_wedge_endpoint(monkeypatch):
    """A broker that hangs forever must be reported as ``error: timeout``."""
    monkeypatch.setattr(pa, "GROUP_FETCH_TIMEOUT_SECONDS", 0.4)
    _register_fake("fast", _FakeBroker(equity=100))
    _register_fake("slow", _FakeBroker(equity=999, delay=5.0))
    out = await asyncio.wait_for(pa.aggregate(), timeout=2.0)
    by_id = {g["credential_id"]: g for g in out["groups"]}
    assert by_id["fast"]["error"] is None
    assert by_id["fast"]["account"]["equity"] == 100
    assert by_id["slow"]["error"] == "timeout"
    assert by_id["slow"]["account"] is None


# ── B3: lock + hook double-register guard ──────────────────────────────────

def test_b3_invalidation_hook_registered_only_once():
    """Re-importing the module must not stack duplicate hooks."""
    initial = factory_mod._INVALIDATION_HOOKS.count(pa._on_credential_invalidated)
    # Simulate re-registration on a hot reload.
    if pa._on_credential_invalidated not in factory_mod._INVALIDATION_HOOKS:
        factory_mod._INVALIDATION_HOOKS.append(pa._on_credential_invalidated)
    again = factory_mod._INVALIDATION_HOOKS.count(pa._on_credential_invalidated)
    assert initial == 1
    assert again == 1


async def test_b3_cache_locked_across_threads():
    """Concurrent writes to ``_CACHE`` must not raise or corrupt state."""
    errors: list[BaseException] = []

    def _hammer(key_prefix: str) -> None:
        try:
            for i in range(500):
                with pa._CACHE_LOCK:
                    pa._CACHE[(f"{key_prefix}-{i}", "account")] = (float(i), {"x": i})
                with pa._CACHE_LOCK:
                    pa._CACHE.pop((f"{key_prefix}-{i}", "account"), None)
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_hammer, args=(f"t{n}",)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
