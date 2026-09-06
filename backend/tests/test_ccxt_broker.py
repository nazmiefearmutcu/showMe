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
        def __init__(self, config=None, **_kw):
            self.opts = dict(config or {})
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


def test_real_ccxt_construction_no_network() -> None:
    """Regression: CcxtBroker must construct against the real ccxt package
    without raising. Catches the 'ccxt.async_support not auto-loaded' class
    of defect at unit-test time so it can't ship.

    Constructing does not hit the network — ccxt only does that on first
    fetch_markets() call. We assert .name + the underlying exchange's
    name attribute as a smoke."""
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
    )
    assert broker.name == "ccxt:binance"
    # ccxt exchange instances expose .id; verifies we wired the right
    # underlying exchange.
    assert getattr(broker._ex, "id", None) == "binance"


# ── F2 fix: equity resolves in the bot symbol's QUOTE currency ───────────


def test_quote_of_infers_quote_from_symbol() -> None:
    """F2: slash form → tail is the quote; unslashed → longest known-quote
    suffix; unknown / empty → None (legacy labelled fallback path)."""
    assert CcxtBroker._quote_of("BTC/USDT") == "USDT"
    assert CcxtBroker._quote_of("ETH/USDC") == "USDC"
    assert CcxtBroker._quote_of("BTCUSDT") == "USDT"
    assert CcxtBroker._quote_of("ETHFDUSD") == "FDUSD"  # not USD
    assert CcxtBroker._quote_of("ETHBUSD") == "BUSD"    # not USD
    assert CcxtBroker._quote_of("AAPL") is None
    assert CcxtBroker._quote_of("BTC") is None
    assert CcxtBroker._quote_of("") is None
    assert CcxtBroker._quote_of(None) is None


def _broker_with_balances(total: dict, free: dict) -> CcxtBroker:
    fake = _fake_ccxt_module()
    broker = CcxtBroker(
        exchange_id="binance",
        credentials={"api_key": "k", "api_secret": "s"},
        permissions=("read",),
        ccxt_module=fake,
    )
    broker._ex.fetch_balance = AsyncMock(return_value={
        "info": {},
        "free": free,
        "total": total,
    })
    return broker


@pytest.mark.asyncio
async def test_account_symbol_resolves_quote_currency_equity() -> None:
    """F2: with a symbol, equity/cash come from the QUOTE balance — not
    the numerically-largest balance (1M SHIB must never read as $1M)."""
    broker = _broker_with_balances(
        total={"SHIB": 1_000_000.0, "USDT": 100.0},
        free={"SHIB": 1_000_000.0, "USDT": 40.0},
    )
    acct = await broker.account("BTC/USDT")
    assert acct["equity"] == 100.0
    assert acct["cash"] == 40.0
    assert acct["buying_power"] == 40.0
    assert acct["currency"] == "USDT"
    assert acct["equity_basis"] == "quote_balance"


@pytest.mark.asyncio
async def test_account_missing_quote_balance_reports_zero() -> None:
    """F2: quote currency absent from the balances → equity=0/cash=0
    (downstream qty resolution treats 0 as no-trade), never a max-pick
    from some other currency."""
    broker = _broker_with_balances(
        total={"SHIB": 1_000_000.0},
        free={"SHIB": 1_000_000.0},
    )
    acct = await broker.account("BTC/USDT")
    assert acct["equity"] == 0.0
    assert acct["cash"] == 0.0
    assert acct["currency"] == "USDT"


@pytest.mark.asyncio
async def test_account_without_symbol_keeps_labelled_max_pick_fallback() -> None:
    """F2: symbol-less callers keep the legacy max-pick behaviour,
    explicitly labelled via ``equity_basis='max_balance_fallback'``."""
    broker = _broker_with_balances(
        total={"SHIB": 1_000_000.0, "USDT": 100.0},
        free={"SHIB": 1_000_000.0, "USDT": 40.0},
    )
    acct = await broker.account()
    assert acct["equity"] == 1_000_000.0
    assert acct["cash"] == 1_000_000.0
    assert acct["currency"] == "SHIB"
    assert acct["equity_basis"] == "max_balance_fallback"


@pytest.mark.asyncio
async def test_account_accepts_symbol_for_unslashed_quote_suffix() -> None:
    """F2: unslashed symbols resolve the quote via suffix match."""
    broker = _broker_with_balances(
        total={"SHIB": 1_000_000.0, "USDT": 250.0},
        free={"SHIB": 0.0, "USDT": 250.0},
    )
    acct = await broker.account("BTCUSDT")
    assert acct["equity"] == 250.0
    assert acct["currency"] == "USDT"
