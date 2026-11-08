"""BRIEF#1 — the default watchlist is the user's positions plus saved watchlists (p1a-g05).

Before the fix BRIEF with no params used a hard-coded AAPL/MSFT/BTCUSDT list and
never read the portfolio, so NVDA, SPY, TLT, GLD and BTC-USD never appeared.
TOP (news) and the sentiment stamper are stubbed; no network is used.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import brief as brief_mod
from showme.engine.functions.news import top as top_mod

_PORTFOLIO = [
    ("AAPL", AssetClass.EQUITY),
    ("MSFT", AssetClass.EQUITY),
    ("NVDA", AssetClass.EQUITY),
    ("SPY", AssetClass.ETF),
    ("TLT", AssetClass.ETF),
    ("GLD", AssetClass.ETF),
    ("BTC-USD", AssetClass.CRYPTO),
]


class _Position:
    def __init__(self, symbol, asset_class):
        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture
def offline(monkeypatch):
    """Stub portfolio, watchlists, TOP and the sentiment stamper; record TOP calls."""
    state = {"positions": [], "watchlists": []}

    class _Portfolio:
        def __init__(self):
            self.positions = [_Position(s, ac) for s, ac in state["positions"]]

        def import_legacy_crypto(self):
            return None

    def _lists(user_id="local"):
        return list(state["watchlists"])

    calls: list[dict] = []

    async def _top_execute(self, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(data={"items": []}, sources=[], metadata={})

    async def _stamp(items):
        return items, None

    monkeypatch.setattr(brief_mod, "PortfolioState", _Portfolio, raising=False)
    monkeypatch.setattr(brief_mod, "list_watchlists", _lists, raising=False)
    monkeypatch.setattr(top_mod.TOPFunction, "execute", _top_execute)
    monkeypatch.setattr("showme.finbert_analyzer.stamp_items", _stamp)
    return state, calls


def test_default_watchlist_is_the_portfolio_positions(offline):
    state, calls = offline
    state["positions"] = _PORTFOLIO
    res = _run(brief_mod.BRIEFFunction(None).execute())
    data = res.data
    assert data["watchlist"] == [s for s, _ in _PORTFOLIO]
    assert "BTCUSDT" not in data["watchlist"]
    searched = {c.get("symbol") for c in calls if c.get("symbol")}
    assert searched == {s for s, _ in _PORTFOLIO}, searched
    assert data["watchlist_source"] == "positions_and_watchlists"


def test_saved_watchlists_are_merged_with_positions(offline):
    state, _ = offline
    state["positions"] = [("AAPL", AssetClass.EQUITY)]
    state["watchlists"] = [{"name": "tech", "symbols": ["nvda", "AAPL"]}]
    res = _run(brief_mod.BRIEFFunction(None).execute())
    assert res.data["watchlist"] == ["AAPL", "NVDA"]


def test_no_positions_and_no_watchlist_is_an_honest_needs_input(offline):
    _, calls = offline
    res = _run(brief_mod.BRIEFFunction(None).execute())
    data = res.data
    assert data["status"] == "needs_input", data["status"]
    assert data["watchlist"] == []
    assert data["articles"] == []
    assert data["next_actions"], "needs_input must say what to do"
    assert "AAPL" not in data["markdown"]
    assert calls == [], "no news calls should be made without symbols"


def test_explicit_watchlist_param_still_wins(offline):
    state, _ = offline
    state["positions"] = _PORTFOLIO
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["ibm"]))
    assert res.data["watchlist"] == ["IBM"]
    assert res.data["watchlist_source"] == "input"
