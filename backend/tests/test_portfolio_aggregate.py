"""portfolio_aggregate.aggregate() unit tests with fake brokers."""
from __future__ import annotations


import pytest

from showme.brokers import factory as factory_mod
from showme.brokers.base import OrderSide, Position
from showme import portfolio_aggregate as pa


@pytest.fixture(autouse=True)
def _isolate():
    pa._CACHE.clear()
    snap_reg = dict(factory_mod._REGISTRY)
    snap_dyn = dict(factory_mod._DYNAMIC)
    snap_live = dict(factory_mod._LIVE)
    # Actively wipe per-credential state leaked from prior tests so this
    # suite sees a clean factory regardless of run order.
    factory_mod._DYNAMIC.clear()
    factory_mod._LIVE.clear()
    for name in list(factory_mod._REGISTRY.keys()):
        if ":" in name:
            factory_mod._REGISTRY.pop(name, None)
    yield
    pa._CACHE.clear()
    factory_mod._REGISTRY.clear()
    factory_mod._REGISTRY.update(snap_reg)
    factory_mod._DYNAMIC.clear()
    factory_mod._DYNAMIC.update(snap_dyn)
    factory_mod._LIVE.clear()
    factory_mod._LIVE.update(snap_live)


class _FakeBroker:
    name = "ccxt:binance"

    def __init__(self, equity=100.0, currency="USDT", positions=None, orders=None,
                 fail=False):
        self.account_calls = 0
        self.position_calls = 0
        self._equity = equity
        self._currency = currency
        self._positions = positions or [
            Position(symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.5,
                     entry_price=60000.0, current_price=61000.0, unrealized_pnl=500.0),
        ]
        self._orders = orders or []
        self._fail = fail

    async def account(self):
        self.account_calls += 1
        if self._fail:
            raise RuntimeError("boom")
        return {"cash": self._equity, "equity": self._equity,
                "buying_power": self._equity, "currency": self._currency, "raw": {}}

    async def list_positions(self):
        self.position_calls += 1
        if self._fail:
            raise RuntimeError("boom")
        return list(self._positions)

    async def list_orders(self, *, status="open", limit=100):
        return list(self._orders)


def _register_fake(credential_id: str, broker, exchange_id="binance", label="main",
                   permissions=("read",)) -> None:
    name = f"{exchange_id}:{credential_id}"
    factory_mod._REGISTRY[name] = lambda b=broker: b
    factory_mod._DYNAMIC[credential_id] = name
    # 2026-05-23: align with the new ``register_broker`` behaviour — the
    # factory's per-name cache (``_LIVE``) is evicted on re-register so a
    # credential rotation surfaces the new broker. ``_register_fake``
    # writes ``_REGISTRY`` directly so we must invalidate the cache here.
    factory_mod._LIVE.pop(name, None)


@pytest.mark.asyncio
async def test_aggregate_returns_one_group_per_credential():
    _register_fake("abc", _FakeBroker(equity=100))
    _register_fake("def", _FakeBroker(equity=200, currency="USDT"))
    out = await pa.aggregate(credential_ids=None, include_orders=False)
    assert isinstance(out, dict)
    assert len(out["groups"]) == 2
    by_id = {g["credential_id"]: g for g in out["groups"]}
    assert by_id["abc"]["account"]["equity"] == 100
    assert by_id["def"]["account"]["equity"] == 200
    assert out["totals"]["equity_by_currency"]["USDT"] == 300


@pytest.mark.asyncio
async def test_aggregate_partial_failure():
    _register_fake("ok", _FakeBroker(equity=100))
    _register_fake("bad", _FakeBroker(fail=True))
    out = await pa.aggregate(credential_ids=None, include_orders=False)
    by_id = {g["credential_id"]: g for g in out["groups"]}
    assert by_id["ok"]["error"] is None
    assert by_id["ok"]["account"]["equity"] == 100
    assert by_id["bad"]["error"] is not None
    assert "boom" in by_id["bad"]["error"]


@pytest.mark.asyncio
async def test_aggregate_filter_by_credential_ids():
    _register_fake("abc", _FakeBroker(equity=100))
    _register_fake("def", _FakeBroker(equity=200))
    out = await pa.aggregate(credential_ids=["abc"], include_orders=False)
    assert [g["credential_id"] for g in out["groups"]] == ["abc"]


@pytest.mark.asyncio
async def test_aggregate_cache_hits_within_ttl():
    b = _FakeBroker(equity=100)
    _register_fake("abc", b)
    await pa.aggregate(credential_ids=None, include_orders=False)
    assert b.account_calls == 1
    await pa.aggregate(credential_ids=None, include_orders=False)
    assert b.account_calls == 1


@pytest.mark.asyncio
async def test_aggregate_cache_invalidated_by_factory_hook():
    b = _FakeBroker(equity=100)
    _register_fake("abc", b)
    await pa.aggregate(credential_ids=None, include_orders=False)
    assert b.account_calls == 1
    pa._on_credential_invalidated("abc")
    new_broker = _FakeBroker(equity=999)
    _register_fake("abc", new_broker)
    out = await pa.aggregate(credential_ids=None, include_orders=False)
    assert out["groups"][0]["account"]["equity"] == 999


@pytest.mark.asyncio
async def test_include_orders_skipped_by_default():
    b = _FakeBroker()
    _register_fake("abc", b)
    out = await pa.aggregate(credential_ids=None, include_orders=False)
    assert out["groups"][0]["orders"] == []


@pytest.mark.asyncio
async def test_include_orders_true_fetches_orders():
    from showme.brokers.base import Order, OrderSide, OrderStatus, OrderType, TimeInForce
    order = Order(id="o1", symbol="BTC/USDT", side=OrderSide.BUY, quantity=0.1,
                  order_type=OrderType.LIMIT, time_in_force=TimeInForce.GTC,
                  limit_price=60000.0, status=OrderStatus.NEW)
    b = _FakeBroker(orders=[order])
    _register_fake("abc", b)
    out = await pa.aggregate(credential_ids=None, include_orders=True)
    assert len(out["groups"][0]["orders"]) == 1
    assert out["groups"][0]["orders"][0]["id"] == "o1"
