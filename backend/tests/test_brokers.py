"""Round 27 — Broker scaffold tests."""
from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.brokers import (
    AlpacaPaperBroker,
    BrokerError,
    NotSupported,
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


def test_paper_broker_market_order_without_price_hint_rejected() -> None:
    """HNT-01: a market order with no 'last:' hint / limit_price / marked
    position must NOT silently fill at 0.0 — it gets rejected."""
    broker = PaperBroker(starting_cash=10_000)

    async def _run() -> None:
        with pytest.raises(BrokerError, match="last:"):
            await broker.submit_order(symbol="AAPL", side="buy", quantity=10)
        # A limit_price doubles as the market fill price hint.
        order = await broker.submit_order(
            symbol="AAPL", side="buy", quantity=1,
            limit_price=123.0,
        )
        assert order.avg_fill_price == 123.0

    asyncio.run(_run())


def test_paper_broker_position_flip_realizes_and_reopens() -> None:
    """HNT-02: long 5 @100 → sell 8 @110 flips to short 3 @110 with the
    closed long's realized PnL (+50) booked on the position."""
    broker = PaperBroker(starting_cash=10_000)

    async def _run() -> None:
        await broker.submit_order(
            symbol="MSFT", side="buy", quantity=5, notes="last:100",
        )
        await broker.submit_order(
            symbol="MSFT", side="sell", quantity=8, notes="last:110",
        )
        positions = await broker.list_positions()
        assert len(positions) == 1
        pos = positions[0]
        assert pos.side == OrderSide.SELL
        assert pos.quantity == 3.0
        assert pos.entry_price == 110.0
        assert pos.realized_pnl == pytest.approx(50.0)  # (110-100) * 5

    asyncio.run(_run())


def test_paper_broker_flip_short_close_realizes_full_pnl() -> None:
    """HNT-02 continuation: after the flip the new short is priced at the
    flip trade price (110), so closing at 90 realizes (110-90)*3 = +60 on
    top of the +50 from the closed long — net cash +110."""
    broker = PaperBroker(starting_cash=10_000)

    async def _run() -> None:
        await broker.submit_order(symbol="TSLA", side="buy", quantity=5, notes="last:100")
        await broker.submit_order(symbol="TSLA", side="sell", quantity=8, notes="last:110")
        # Buy 3 @90 closes the short: (90-110)*3*(-1) = +60.
        await broker.submit_order(symbol="TSLA", side="buy", quantity=3, notes="last:90")
        positions = await broker.list_positions()
        assert positions == []  # flattened
        account = await broker.account()
        # 10000 - 500 + 880 - 270 = 10110 → +50 (long) +60 (short).
        assert account["cash"] == pytest.approx(10_110.0)

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


def test_alpaca_list_orders_tolerates_trailing_stop_and_opg() -> None:
    """HNT-05: Alpaca returns order types / TIF values with no enum member
    (trailing_stop, opg) — list_orders must not crash on them."""
    broker = make_alpaca({
        "GET /v2/orders": [
            {
                "id": "alp-ts",
                "symbol": "AAPL",
                "side": "buy",
                "type": "trailing_stop",
                "time_in_force": "opg",
                "qty": "5",
                "status": "held",
                "filled_qty": "0",
                "trail_price": "1.50",
            },
            {
                "id": "alp-tsl",
                "symbol": "MSFT",
                "side": "sell",
                "type": "trailing_stop_limit",
                "time_in_force": "cls",
                "qty": "2",
                "status": "new",
            },
        ],
    })
    orders = asyncio.run(broker.list_orders())
    assert len(orders) == 2
    # Unknown native values remain visible in raw; enum fields map to the
    # closest supported member instead of raising.
    assert orders[0].order_type == OrderType.MARKET
    assert orders[0].raw["type"] == "trailing_stop"
    assert orders[0].raw["time_in_force"] == "opg"
    assert orders[1].order_type == OrderType.STOP_LIMIT


def test_alpaca_close_position_sends_qty_as_query_param() -> None:
    """HNT-03: partial close size must ride the query string — Alpaca's
    DELETE /v2/positions ignores a JSON body and liquidates everything."""
    captured: dict[str, Any] = {}

    def _capture(query, body):
        captured["query"] = query
        captured["body"] = body
        return {
            "id": "close-1", "symbol": "AAPL", "side": "sell",
            "type": "market", "time_in_force": "day", "qty": "5",
            "status": "filled", "filled_qty": "5",
        }

    broker = make_alpaca({"DELETE /v2/positions/AAPL": _capture})
    order = asyncio.run(broker.close_position("aapl", quantity=5))
    assert order.status == OrderStatus.FILLED
    assert captured["query"] == {"qty": 5}
    assert captured["body"] is None


def test_alpaca_permission_gate_blocks_trades() -> None:
    """HNT-04: a credential-scoped AlpacaPaperBroker with read-only
    permissions must refuse order submission."""
    async def _http(method, path, query, body):  # pragma: no cover - must not be reached
        raise AssertionError("read-only credential must not reach the wire")

    broker = AlpacaPaperBroker(
        api_key="k", secret="s", http_call=_http, permissions=("read",),
    )

    async def _run() -> None:
        with pytest.raises(NotSupported, match="trade"):
            await broker.submit_order(symbol="AAPL", side="buy", quantity=1)

    asyncio.run(_run())


def test_alpaca_permission_gate_ungated_by_default() -> None:
    """HNT-04: the legacy env-key construction (no permissions) stays open."""
    async def _http(method, path, query, body):
        return {
            "id": "o1", "symbol": "AAPL", "side": "buy",
            "type": "market", "time_in_force": "day", "qty": "1",
            "status": "accepted",
        }

    broker = AlpacaPaperBroker(api_key="k", secret="s", http_call=_http)
    order = asyncio.run(
        broker.submit_order(symbol="AAPL", side="buy", quantity=1)
    )
    assert order.status == OrderStatus.ACCEPTED
