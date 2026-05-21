"""CcxtBroker unit tests with a mocked ccxt module."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from showme.brokers import OrderSide, OrderStatus, OrderType, TimeInForce
from showme.brokers.base import NotSupported
from showme.brokers.ccxt_broker import CcxtBroker


def _fake_ccxt_module() -> SimpleNamespace:
    """Return a SimpleNamespace whose ``.async_support.binance`` (etc.)
    is a constructable factory returning a mock exchange instance."""

    class _Exchange:
        def __init__(self, **kwargs):
            self.opts = kwargs
            self.fetch_balance = AsyncMock(return_value={
                "info": {"raw": True},
                "free": {"USDT": 100.0},
                "used": {"USDT": 0.0},
                "total": {"USDT": 100.0},
            })
            self.fetch_positions = AsyncMock(return_value=[
                {"symbol": "BTC/USDT", "side": "long", "contracts": 0.5,
                 "entryPrice": 60000.0, "markPrice": 61000.0, "unrealizedPnl": 500.0,
                 "info": {}},
            ])
            self.fetch_open_orders = AsyncMock(return_value=[])
            self.create_order = AsyncMock(return_value={
                "id": "order-1", "symbol": "BTC/USDT", "side": "buy",
                "type": "market", "amount": 0.1, "filled": 0.1,
                "status": "closed", "timeInForce": "GTC",
                "average": 61010.0, "datetime": "2026-05-21T10:00:00Z",
            })
            self.cancel_order = AsyncMock(return_value={"id": "order-1", "status": "canceled"})
            self.close = AsyncMock()

    return SimpleNamespace(async_support=SimpleNamespace(binance=_Exchange))


@pytest.mark.asyncio
async def test_account_returns_normalised_payload() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    acct = await broker.account()
    assert acct["cash"] == 100.0
    assert acct["equity"] == 100.0
    assert acct["buying_power"] == 100.0
    assert acct["currency"] == "USDT"


@pytest.mark.asyncio
async def test_list_positions_filters_zero_size() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    rows = await broker.list_positions()
    assert len(rows) == 1
    assert rows[0].symbol == "BTC/USDT"
    assert rows[0].quantity == 0.5
    assert rows[0].side == OrderSide.BUY  # ccxt "long" → BUY in our model


@pytest.mark.asyncio
async def test_submit_order_blocked_on_read_only_credential() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    with pytest.raises(NotSupported):
        await broker.submit_order(
            symbol="BTC/USDT", side="buy", quantity=0.1,
            order_type=OrderType.MARKET, time_in_force=TimeInForce.GTC,
        )


@pytest.mark.asyncio
async def test_submit_order_allowed_with_trade_permission() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read", "trade"),
        ccxt_module=fake,
    )
    order = await broker.submit_order(
        symbol="BTC/USDT", side="buy", quantity=0.1,
        order_type=OrderType.MARKET, time_in_force=TimeInForce.GTC,
    )
    assert order.id == "order-1"
    assert order.symbol == "BTC/USDT"
    assert order.status == OrderStatus.FILLED


@pytest.mark.asyncio
async def test_cancel_order_returns_true_on_success() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read", "trade"),
        ccxt_module=fake,
    )
    assert await broker.cancel_order("order-1") is True


@pytest.mark.asyncio
async def test_close_position_blocked_on_read_only() -> None:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    with pytest.raises(NotSupported):
        await broker.close_position("BTC/USDT")
