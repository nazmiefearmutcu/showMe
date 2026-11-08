"""TSOX#2: a yield-quoted symbol must not take a price-unit limit silently.

US10Y (and the other US1M..US30Y symbols in server.BOND_SYMBOLS) is a yield
quote, not a price. TSOX used to echo a LIMIT price of 110.015625 for US10Y as
a valid preview. There is no yield-to-price conversion here (it needs the bond's
coupon and maturity, which TSOX does not source), so the ticket now rejects the
LIMIT with an explicit input_error on price, and a MARKET preview carries a
warning that the quote convention is yield.

Offline: the broker is a recording fake; nothing reaches a venue.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.trade._funcs import TSOXFunction

US10Y = Instrument(symbol="US10Y", asset_class=AssetClass.BOND)
ZN = Instrument(symbol="ZN=F", asset_class=AssetClass.DERIVATIVE)


class _RecordingBroker:
    name = "recording_broker"

    def __init__(self) -> None:
        self.placed: list[Any] = []

    async def place_order(self, order: Any) -> str:
        self.placed.append(order)
        return f"ord-{len(self.placed)}"


def _tsox() -> tuple[TSOXFunction, _RecordingBroker]:
    fn = TSOXFunction()
    deps = FunctionDeps()
    broker = _RecordingBroker()
    deps.ibkr_broker = broker
    fn.deps = deps
    return fn, broker


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_yield_quoted_limit_price_is_rejected_not_previewed() -> None:
    fn, broker = _tsox()
    res = _run(fn.execute(instrument=US10Y, side="BUY", quantity=1, order_type="LIMIT", price=110.015625))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "price"
    assert "yield" in res.data["reason"].lower()
    assert res.data["price"] is None
    assert broker.placed == []


def test_yield_quoted_market_preview_names_the_quote_convention() -> None:
    fn, broker = _tsox()
    res = _run(fn.execute(instrument=US10Y, side="BUY", quantity=1, order_type="MARKET"))
    assert res.data["status"] == "preview"
    assert res.data["price"] is None
    assert any("yield" in w.lower() for w in res.warnings), res.warnings
    assert broker.placed == []


def test_price_quoted_future_limit_is_still_previewed() -> None:
    # ZN=F is quoted in price units, so the 32nds decimal is still accepted.
    fn, _ = _tsox()
    res = _run(fn.execute(instrument=ZN, side="BUY", quantity=1, order_type="LIMIT", price=110.015625))
    assert res.data["status"] == "preview"
    assert res.data["price"] == 110.015625
    assert not any("yield" in w.lower() for w in res.warnings)


@pytest.mark.parametrize("symbol", ["US2Y", "US30Y"])
def test_every_yield_symbol_is_treated_as_yield_quoted(symbol: str) -> None:
    fn, _ = _tsox()
    res = _run(fn.execute(
        instrument=Instrument(symbol=symbol, asset_class=AssetClass.BOND),
        side="SELL", quantity=2, order_type="LIMIT", price=99.5,
    ))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "price"
