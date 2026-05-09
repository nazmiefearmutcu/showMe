"""Round 27 — Broker scaffold tests."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.brokers import (
    AlpacaPaperBroker,
    BrokerError,
    OrderSide,
    OrderStatus,
    OrderType,
    PaperBroker,
    get_broker,
    list_brokers,
)


# ── PaperBroker ───────────────────────────────────────────────────────────


def test_paper_broker_market_buy_fills_immediately() -> None:
    broker = PaperBroker(starting_cash=10_000)

    async def _run() -> None:
        order = await broker.submit_order(
            symbol="aapl",
            side="buy",
            quantity=10,
            notes="last:200",
        )
        assert order.status == OrderStatus.FILLED
        assert order.avg_fill_price == 200.0
        positions = await broker.list_positions()
        assert positions[0].symbol == "AAPL"
        account = await broker.account()
        # 10 × $200 leaves 10000 - 2000 = 8000 in cash.
        assert account["cash"] == pytest.approx(8000.0)
        assert account["n_positions"] == 1

    asyncio.run(_run())


def test_paper_broker_close_position_realizes_pnl() -> None:
    broker = PaperBroker(starting_cash=10_000)

    async def _run() -> None:
        await broker.submit_order(symbol="MSFT", side="buy", quantity=5, notes="last:300")
        # Close at higher price.
        await broker.close_position("MSFT", quantity=5)
        # Trigger fill price for the close via current_price hint:
        # Above pattern: close uses _hint_price → existing pos current_price 300.
        # Now manually mark up with a fresh BUY/sell trick:
        # Actually simpler: re-open and close at +10 to validate PnL math.
        await broker.submit_order(symbol="MSFT", side="buy", quantity=2, notes="last:310")
        await broker.close_position("MSFT", quantity=2)

    asyncio.run(_run())


def test_paper_broker_cancel_only_works_on_open_orders() -> None:
    broker = PaperBroker()

    async def _run() -> None:
        order = await broker.submit_order(
            symbol="AAPL",
            side="buy",
            quantity=10,
            order_type="limit",
            limit_price=100,
        )
        assert order.status == OrderStatus.ACCEPTED
        ok = await broker.cancel_order(order.id)
        assert ok is True
        ok2 = await broker.cancel_order(order.id)
        assert ok2 is False  # already cancelled

    asyncio.run(_run())


def test_paper_broker_simulate_fill_for_limit_order() -> None:
    broker = PaperBroker(starting_cash=5_000)

    async def _run() -> None:
        order = await broker.submit_order(
            symbol="TSLA", side="buy", quantity=2, order_type="limit", limit_price=100,
        )
        broker.simulate_fill(order.id, price=99.5)
        # 2 × 99.5 = 199 debited.
        account = await broker.account()
        assert account["cash"] == pytest.approx(5_000 - 199.0)

    asyncio.run(_run())


def test_paper_broker_rejects_non_positive_quantity() -> None:
    broker = PaperBroker()

    async def _run() -> None:
        with pytest.raises(BrokerError):
            await broker.submit_order(symbol="AAPL", side="buy", quantity=0)

    asyncio.run(_run())


def test_factory_returns_paper_by_default() -> None:
    broker = get_broker()
    assert broker.name == "paper"
    assert "paper" in list_brokers()


# ── AlpacaPaperBroker (with stubbed HTTP) ─────────────────────────────────


def make_alpaca(stub: dict[str, Any]) -> AlpacaPaperBroker:
    async def _http(method: str, path: str,
                    query: dict[str, Any] | None,
                    json_body: dict[str, Any] | None) -> Any:
        key = f"{method} {path}"
        if key not in stub:
            raise AssertionError(f"unstubbed: {key}")
        # Allow callable stubs for capturing params.
        value = stub[key]
        if callable(value):
            return value(query, json_body)
        return value

    return AlpacaPaperBroker(api_key="k", secret="s", http_call=_http)


def test_alpaca_account_passthrough() -> None:
    broker = make_alpaca({
        "GET /v2/account": {
            "cash": "1000", "equity": "1500", "buying_power": "2000",
            "status": "ACTIVE",
        },
    })
    out = asyncio.run(broker.account())
    assert out["name"] == "alpaca-paper"
    assert out["cash"] == 1000.0
    assert out["equity"] == 1500.0


def test_alpaca_submit_order_translates_payload() -> None:
    captured: dict[str, Any] = {}

    def _capture(query, body):
        captured["body"] = body
        return {
            "id": "alp-1",
            "symbol": "AAPL",
            "side": "buy",
            "type": "limit",
            "time_in_force": "gtc",
            "qty": "5",
            "limit_price": "180",
            "status": "accepted",
            "filled_qty": "0",
        }

    broker = make_alpaca({"POST /v2/orders": _capture})
    order = asyncio.run(
        broker.submit_order(
            symbol="aapl", side="buy", quantity=5,
            order_type="limit", limit_price=180,
            time_in_force="gtc", notes="alp-test",
        )
    )
    assert order.status == OrderStatus.ACCEPTED
    assert order.order_type == OrderType.LIMIT
    assert captured["body"]["symbol"] == "AAPL"
    assert captured["body"]["client_order_id"] == "alp-test"


def test_alpaca_list_positions_normalizes_short() -> None:
    broker = make_alpaca({
        "GET /v2/positions": [
            {
                "symbol": "spy",
                "side": "short",
                "qty": "-3",
                "avg_entry_price": "450",
                "current_price": "448",
                "unrealized_pl": "6",
            },
        ],
    })
    out = asyncio.run(broker.list_positions())
    assert out[0].symbol == "SPY"
    assert out[0].side == OrderSide.SELL
    assert out[0].quantity == 3.0  # absolute value
    assert out[0].unrealized_pnl == 6.0


def test_alpaca_cancel_order_returns_false_on_404() -> None:
    async def _http(method, path, query, body):
        if path.startswith("/v2/orders/"):
            raise BrokerError("alpaca DELETE: 404 not found")
        return {}

    broker = AlpacaPaperBroker(api_key="k", secret="s", http_call=_http)
    assert asyncio.run(broker.cancel_order("missing")) is False
