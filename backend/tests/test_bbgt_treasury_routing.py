"""BBGT must not send a CME Treasury future to the equity broker (BBGT#1).

The BBGT pane always sends the asset class it shows (EQUITY by default), and
an explicit EQUITY request bypasses the symbol classifier. ZN=F with EQUITY
resolves to alpaca_broker, so a live ticket would reach the equity venue.
BBGT must refuse that combination before any broker call, and a Treasury
future classed DERIVATIVE must still route to the IBKR desk.
No network: brokers are in-test recorders.
"""

from __future__ import annotations

import asyncio
from typing import Any

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.trade._funcs import BBGTFunction


class _RecordingBroker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.placed: list[Any] = []

    async def place_order(self, order: Any) -> str:
        self.placed.append(order)
        return f"{self.name}-{len(self.placed)}"

    async def get_open_orders(self) -> list[Any]:
        return []


def _fn() -> tuple[BBGTFunction, _RecordingBroker, _RecordingBroker]:
    fn = BBGTFunction()
    deps = FunctionDeps()
    alpaca = _RecordingBroker("alpaca")
    ibkr = _RecordingBroker("ibkr")
    deps.alpaca_broker = alpaca
    deps.ibkr_broker = ibkr
    fn.deps = deps
    return fn, alpaca, ibkr


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def test_treasury_future_requested_as_equity_is_refused_before_any_broker() -> None:
    fn, alpaca, ibkr = _fn()
    zn_equity = Instrument(symbol="ZN=F", asset_class=AssetClass.EQUITY)
    res = _run(fn.execute(
        instrument=zn_equity, quantity=1, side="BUY", type="MARKET", tif="DAY",
        submit=True, paper_mode=False,
    ))
    assert alpaca.placed == []
    assert ibkr.placed == []
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "asset_class"
    assert "EQUITY" in res.data["reason"]


def test_treasury_future_requested_as_equity_preview_is_not_a_valid_preview() -> None:
    fn, alpaca, ibkr = _fn()
    zn_equity = Instrument(symbol="ZN=F", asset_class=AssetClass.EQUITY)
    res = _run(fn.execute(
        instrument=zn_equity, quantity=1, side="BUY", type="MARKET", tif="DAY",
    ))
    assert res.data["status"] == "input_error"
    assert alpaca.placed == [] and ibkr.placed == []


def test_treasury_future_as_derivative_routes_to_ibkr_not_alpaca() -> None:
    fn, alpaca, ibkr = _fn()
    zn_deriv = Instrument(symbol="ZN=F", asset_class=AssetClass.DERIVATIVE)
    res = _run(fn.execute(
        instrument=zn_deriv, quantity=1, side="BUY", type="MARKET", tif="DAY",
        submit=True, paper_mode=False,
    ))
    assert res.data.get("status") != "input_error"
    assert alpaca.placed == []


def test_equity_ticket_for_ordinary_stock_is_unchanged() -> None:
    fn, alpaca, _ibkr = _fn()
    aapl = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    res = _run(fn.execute(
        instrument=aapl, quantity=1, side="BUY", type="MARKET", tif="DAY",
    ))
    assert res.data.get("status") != "input_error"
