"""EMSX#4 (wc3-g05): a futures ticket never routes as an equity order.

The caller-declared asset_class overrides the symbol resolver. A ZN=F ticket
declared EQUITY must be refused before any broker is contacted, instead of
reaching the equity (Alpaca) broker. Broker and network are faked.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.trade._funcs import EMSXFunction


class _Broker:
    def __init__(self, name: str) -> None:
        self.name = name
        self.orders: list[Any] = []

    async def place_order(self, order: Any) -> str:
        self.orders.append(order)
        return "order-1"


def _run(instrument: Instrument, **params: Any):
    alpaca, ibkr = _Broker("alpaca_broker"), _Broker("ibkr_broker")
    deps = SimpleNamespace(alpaca_broker=alpaca, ibkr_broker=ibkr)
    fn = EMSXFunction(deps)
    res = asyncio.run(fn.execute(instrument=instrument, quantity=1, side="BUY", type="MARKET", **params))
    return res, alpaca, ibkr


def test_zn_future_declared_equity_is_refused_and_not_sent_to_alpaca() -> None:
    inst = Instrument(symbol="ZN=F", asset_class=AssetClass.EQUITY)
    res, alpaca, ibkr = _run(inst, submit=True, paper_mode=False)
    # RED before fix: the ticket reached alpaca_broker as an EQUITY order.
    assert alpaca.orders == [], "futures ticket was sent to the equity broker"
    assert ibkr.orders == []
    assert res.data["status"] == "input_error", res.data
    assert res.data["asset_class"] == "EQUITY"
    assert "ZN=F" in res.data["reason"]


def test_zn_future_declared_equity_preview_is_refused() -> None:
    inst = Instrument(symbol="ZN=F", asset_class=AssetClass.EQUITY)
    res, alpaca, ibkr = _run(inst)
    assert res.data["status"] == "input_error", res.data
    assert res.data.get("broker") is None


def test_zn_future_declared_derivative_still_previews_on_ibkr_route() -> None:
    inst = Instrument(symbol="ZN=F", asset_class=AssetClass.DERIVATIVE)
    res, alpaca, ibkr = _run(inst, submit=True, paper_mode=False)
    assert alpaca.orders == []
    assert len(ibkr.orders) == 1, res.data
    assert res.data.get("status") != "input_error", res.data


def test_tsox_inherits_emsx_without_futures_guard() -> None:
    """EMSX#4 is scoped to EMSX: TSOX (a subclass sharing execute) keeps its behaviour.

    The futures-class refusal was added to the shared EMSX execute path, which
    TSOX/FXGO/BBGT inherit. Only EMSX may refuse here; TSOX must not return the
    EMSX#4 futures input_error for a ZN=F ticket.
    """
    from showme.engine.functions.trade._funcs import TSOXFunction

    inst = Instrument(symbol="ZN=F", asset_class=AssetClass.EQUITY)
    alpaca, ibkr = _Broker("alpaca_broker"), _Broker("ibkr_broker")
    deps = SimpleNamespace(alpaca_broker=alpaca, ibkr_broker=ibkr)
    res = asyncio.run(TSOXFunction(deps).execute(instrument=inst, quantity=1, side="BUY", type="MARKET"))
    reason = str(res.data.get("reason", ""))
    assert "is a futures contract but the ticket asset_class" not in reason, res.data
    assert alpaca.orders == [] and ibkr.orders == []


def test_equity_symbol_declared_equity_is_unchanged() -> None:
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    res, alpaca, ibkr = _run(inst)
    assert res.data["status"] == "preview", res.data
    assert res.data["asset_class"] == "EQUITY"
