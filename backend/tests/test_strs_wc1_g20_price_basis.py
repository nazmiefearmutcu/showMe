"""STRS#6 — the valuation basis is stated, and a live-mode cost fallback is never silent.

Default mode values positions at average cost (no quote call). With refresh_prices a
missing quote falls back to average cost for that one position. The response must
say which basis each position used (price_basis), report price_source as "mixed"
when some positions fell back, and warn for every fallback. The summary must never
claim live_quote while a position is at cost.

No network: PortfolioState and the yfinance adapter are in-memory fakes.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio import strs as strs_mod


class _Position:
    def __init__(self, symbol: str, asset_class: AssetClass, quantity: float, avg_cost: float):
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)
        self.quantity = quantity
        self.avg_cost = avg_cost


def _use_positions(monkeypatch, positions):
    class _Portfolio:
        def __init__(self):
            self.positions = positions

        def import_legacy_crypto(self):
            return None

    monkeypatch.setattr(strs_mod, "PortfolioState", _Portfolio)


class _FakeQuotes:
    """Answers QUOTE with ``last`` for quoted symbols; raises otherwise. REFDATA raises."""

    def __init__(self, quotes: dict[str, float]):
        self.quotes = quotes

    async def fetch(self, request):
        if request.kind == DataKind.QUOTE and request.instrument.symbol in self.quotes:
            return SimpleNamespace(last=self.quotes[request.instrument.symbol])
        raise RuntimeError("no quote")


def _row(res, symbol):
    return next(r for r in res.data["positions"] if r["symbol"] == symbol)


def test_default_mode_states_average_cost_basis(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10.0, 100.0)])
    res = asyncio.run(strs_mod.STRSFunction().execute(action="scenario", scenario="GFC_2008"))
    assert res.data["price_source"] == "portfolio_state_cost"
    assert _row(res, "AAPL")["price_basis"] == "portfolio_state_cost"
    assert any("average cost" in w for w in res.warnings), res.warnings


def test_compare_default_summary_names_the_basis(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10.0, 100.0)])
    res = asyncio.run(strs_mod.STRSFunction().execute(action="compare"))
    assert res.data["summary"]["price_source"] == "portfolio_state_cost"
    assert any("average cost" in w for w in res.warnings), res.warnings


def test_live_mode_all_quoted_is_live_quote_without_fallback_warnings(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10.0, 100.0)])
    deps = SimpleNamespace(yfinance=_FakeQuotes({"AAPL": 120.0}))
    res = asyncio.run(strs_mod.STRSFunction(deps).execute(
        action="compare", refresh_prices=True, include_sectors=False,
    ))
    assert res.data["summary"]["price_source"] == "live_quote"
    assert not [w for w in res.warnings if "average cost" in w], res.warnings


def test_live_mode_partial_fallback_is_mixed_and_flagged_per_position(monkeypatch):
    _use_positions(monkeypatch, [
        _Position("AAPL", AssetClass.EQUITY, 10.0, 100.0),
        _Position("MSFT", AssetClass.EQUITY, 10.0, 200.0),
    ])
    deps = SimpleNamespace(yfinance=_FakeQuotes({"AAPL": 120.0}))  # MSFT has no quote
    res = asyncio.run(strs_mod.STRSFunction(deps).execute(
        action="scenario", scenario="GFC_2008", refresh_prices=True, include_sectors=False,
    ))
    assert _row(res, "AAPL")["price_basis"] == "live_quote"
    assert _row(res, "MSFT")["price_basis"] == "avg_cost_fallback"
    assert res.data["price_source"] == "mixed"
    assert any("MSFT" in w and "average cost" in w for w in res.warnings), res.warnings
    assert not any(w.startswith("AAPL") and "average cost" in w for w in res.warnings)


def test_live_mode_partial_fallback_summary_is_mixed_in_compare(monkeypatch):
    _use_positions(monkeypatch, [
        _Position("AAPL", AssetClass.EQUITY, 10.0, 100.0),
        _Position("MSFT", AssetClass.EQUITY, 10.0, 200.0),
    ])
    deps = SimpleNamespace(yfinance=_FakeQuotes({"AAPL": 120.0}))
    res = asyncio.run(strs_mod.STRSFunction(deps).execute(
        action="compare", refresh_prices=True, include_sectors=False,
    ))
    assert res.data["summary"]["price_source"] == "mixed"
    assert any("MSFT" in w for w in res.warnings), res.warnings


def test_live_mode_no_quotes_is_stated_as_cost_not_live(monkeypatch):
    _use_positions(monkeypatch, [_Position("AAPL", AssetClass.EQUITY, 10.0, 100.0)])
    deps = SimpleNamespace(yfinance=_FakeQuotes({}))
    res = asyncio.run(strs_mod.STRSFunction(deps).execute(
        action="compare", refresh_prices=True, include_sectors=False,
    ))
    assert res.data["summary"]["price_source"] == "portfolio_state_cost"
    assert any("AAPL" in w and "average cost" in w for w in res.warnings), res.warnings
