"""STRS#2 follow-up: 'yfinance' is listed in sources only when the adapter ran.

With no market data adapter the sector lookup never runs, so a default run must
not claim yfinance as a source; the warning already says the shock was not applied.
The network is never touched: PortfolioState and the adapter are in-memory fakes.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass
from showme.engine.functions.portfolio import strs as strs_mod

from test_strs_wc1_g20_sectors import _Position, _use_positions


def test_default_run_without_adapter_does_not_list_yfinance(monkeypatch) -> None:
    _use_positions(monkeypatch, [
        _Position("AAPL", AssetClass.EQUITY, 10, 150.0),
        _Position("MSFT", AssetClass.EQUITY, 5, 300.0),
    ])
    fn = strs_mod.STRSFunction(FunctionDeps())
    res = asyncio.run(fn.execute(action="scenario", scenario="GFC_2008"))
    assert "yfinance" not in res.sources, res.sources
    assert any("sector lookup unavailable" in w for w in res.warnings), res.warnings


def test_default_run_with_adapter_still_lists_yfinance(monkeypatch) -> None:
    from test_strs_wc1_g20_sectors import _FakeRefdata

    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10, 150.0)])
    fn = strs_mod.STRSFunction(FunctionDeps(yfinance=_FakeRefdata({"AAPL": "Technology"})))
    res = asyncio.run(fn.execute(action="scenario", scenario="GFC_2008"))
    assert "yfinance" in res.sources, res.sources
