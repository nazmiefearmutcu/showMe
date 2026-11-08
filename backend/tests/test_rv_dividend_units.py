"""RV#1 — dividend yield is delivered as a decimal fraction (p1a-g05).

yfinance ``info['dividendYield']`` is in percent units (AAPL 0.32 means 0.32%).
RV must hand the pane a fraction (0.0032) so the pane never has to guess units.
The network is replaced by an in-memory yfinance fake.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.rv import RVFunction


class _FakeYF:
    def __init__(self, raw_by_symbol):
        self._raw = raw_by_symbol

    async def fetch(self, request):
        raw = self._raw[request.instrument.symbol]
        return SimpleNamespace(market_cap=None, extras={"raw": raw})


class _Deps:
    finnhub = None

    def __init__(self, raw_by_symbol):
        self.yfinance = _FakeYF(raw_by_symbol)


def _run_rv(raw_by_symbol, symbol="AAPL", peers=("MSFT",)):
    fn = RVFunction(_Deps(raw_by_symbol))
    inst = Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=inst, peers=list(peers)))


def _row(res, symbol):
    return next(r for r in res.data["rows"] if r["symbol"] == symbol)


def test_rv1_dividend_yield_is_returned_as_fraction():
    res = _run_rv({
        "AAPL": {"dividendYield": 0.32, "trailingPE": 30.0},
        "MSFT": {"dividendYield": 0.74, "trailingPE": 25.0},
    })
    # yfinance 0.32 is percent -> 0.0032 as a fraction (0.32%).
    assert _row(res, "AAPL")["div_yield"] == pytest.approx(0.0032)
    assert _row(res, "MSFT")["div_yield"] == pytest.approx(0.0074)


def test_rv1_missing_dividend_yield_stays_none():
    res = _run_rv({
        "AAPL": {"trailingPE": 30.0},
        "MSFT": {"dividendYield": None, "trailingPE": 25.0},
    })
    assert _row(res, "AAPL")["div_yield"] is None
    assert _row(res, "MSFT")["div_yield"] is None
