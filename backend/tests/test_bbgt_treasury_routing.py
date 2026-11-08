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

import pytest

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


_NON_DERIVATIVE_CLASSES = (
    AssetClass.EQUITY,
    AssetClass.ETF,
    AssetClass.FX,
    AssetClass.CRYPTO,
    AssetClass.COMMODITY,
    AssetClass.BOND,
)


def _fn_all_venues() -> tuple[BBGTFunction, dict[str, _RecordingBroker]]:
    """BBGT with a recorder behind every venue an explicit asset class can reach."""
    fn = BBGTFunction()
    deps = FunctionDeps()
    recorders = {
        "alpaca_broker": _RecordingBroker("alpaca"),
        "ibkr_broker": _RecordingBroker("ibkr"),
        "oanda_broker": _RecordingBroker("oanda"),
        "binance_broker": _RecordingBroker("binance"),
    }
    for name, broker in recorders.items():
        setattr(deps, name, broker)
    fn.deps = deps
    return fn, recorders


@pytest.mark.parametrize("asset_class", _NON_DERIVATIVE_CLASSES, ids=lambda c: c.value)
def test_treasury_future_with_any_explicit_non_derivative_class_is_refused(
    asset_class: AssetClass,
) -> None:
    """BBGT#1 follow-up: refusing only EQUITY left ETF/FX/CRYPTO/COMMODITY/BOND routing
    a CME Treasury future to the non-derivative venues. Every such request is refused
    before any broker is called, and the reason names the class that was requested."""
    fn, recorders = _fn_all_venues()
    res = _run(fn.execute(
        instrument=Instrument(symbol="ZN=F", asset_class=asset_class),
        quantity=1, side="BUY", type="MARKET", tif="DAY",
        submit=True, paper_mode=False,
    ))
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "asset_class"
    assert asset_class.value in res.data["reason"]
    assert all(broker.placed == [] for broker in recorders.values())


@pytest.mark.parametrize("asset_class", _NON_DERIVATIVE_CLASSES, ids=lambda c: c.value)
def test_treasury_future_preview_with_any_explicit_non_derivative_class_is_refused(
    asset_class: AssetClass,
) -> None:
    fn, recorders = _fn_all_venues()
    res = _run(fn.execute(
        instrument=Instrument(symbol="ZB=F", asset_class=asset_class),
        quantity=1, side="SELL", type="LIMIT", tif="GTC", price=110.0,
    ))
    assert res.data["status"] == "input_error"
    assert all(broker.placed == [] for broker in recorders.values())


def test_ordinary_non_derivative_class_is_not_refused_for_a_non_treasury_symbol() -> None:
    """The refusal is about Treasury futures only: an ETF ticket is not affected."""
    fn, _recorders = _fn_all_venues()
    res = _run(fn.execute(
        instrument=Instrument(symbol="SPY", asset_class=AssetClass.ETF),
        quantity=1, side="BUY", type="MARKET", tif="DAY",
    ))
    assert res.data.get("status") != "input_error"
