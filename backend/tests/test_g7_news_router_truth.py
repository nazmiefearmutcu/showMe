"""G7 news-router truth regressions: TLDR and SAT.

Network-free. Quote, news, calendar, LLM and GIBS/Open-Meteo calls are patched
the way the sibling tests patch them, so these pin the routed contract only.
"""

from __future__ import annotations

import asyncio

import pytest

from showme import server
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.news.tldr import TLDRFunction

PORTFOLIO_SYMBOLS = ["AAPL", "MSFT", "NVDA", "SPY", "TLT", "GLD", "BTC-USD"]
PEER_GROUP = ["BTCUSDT", "ETHUSDT", "SOLUSDT"]


class _FakeInstrument:
    def __init__(self, symbol: str) -> None:
        self.symbol = symbol


class _FakePosition:
    def __init__(self, symbol: str) -> None:
        self.instrument = _FakeInstrument(symbol)


class _FakePortfolio:
    symbols: list[str] = list(PORTFOLIO_SYMBOLS)

    def __init__(self, *args, **kwargs) -> None:
        self.positions = [_FakePosition(s) for s in type(self).symbols]

    def import_legacy_crypto(self, *args, **kwargs) -> int:
        return 0


def _patch_offline(monkeypatch) -> None:
    """Patch every network-backed dependency of TLDR to fail or answer locally."""
    import showme.engine.agents.llm_router as llm_mod
    import showme.engine.functions.macro.eco as eco_mod
    import showme.engine.functions.news.top as top_mod
    import showme.engine.portfolio.state as state_mod
    import showme.quotes as quotes_mod

    async def _quote(symbol: str):
        return {"symbol": symbol, "last": 100.0, "previous_close": 100.0,
                "change_pct": 0.0, "source": "test_snapshot"}

    async def _offline(self, *args, **kwargs):
        raise RuntimeError("offline in test")

    monkeypatch.setattr(quotes_mod, "fetch_quote_snapshot", _quote)
    monkeypatch.setattr(state_mod, "PortfolioState", _FakePortfolio)
    monkeypatch.setattr(top_mod.TOPFunction, "execute", _offline)
    monkeypatch.setattr(eco_mod.ECOFunction, "execute", _offline)
    monkeypatch.setattr(llm_mod.LLMRouter, "complete", _offline)


def _tldr_index(monkeypatch) -> None:
    monkeypatch.setattr(
        server,
        "_load_function_index",
        lambda: [server.FunctionIndexEntry(code="TLDR", name="Daily TL;DR", category="news", asset_classes=[])],
    )


def test_tldr_default_route_does_not_inject_peer_symbols(monkeypatch) -> None:
    """TLDR#1: the routed layer must not turn the agent peer group into the
    user's watchlist when the caller sent no symbols."""
    _tldr_index(monkeypatch)
    routed = server._route_function_params("TLDR", {})
    assert not routed.get("symbols"), f"peer group injected: {routed.get('symbols')}"


def test_tldr_routed_default_summarises_portfolio_not_peer_group(monkeypatch) -> None:
    """TLDR#1 end to end: the default routed call must describe the portfolio."""
    _patch_offline(monkeypatch)
    _FakePortfolio.symbols = list(PORTFOLIO_SYMBOLS)
    _tldr_index(monkeypatch)
    routed = server._route_function_params("TLDR", {})
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(**routed))
    assert result.data["watchlist"] == PORTFOLIO_SYMBOLS
    assert not set(result.data["watchlist"]) & set(PEER_GROUP)


def test_tldr_explicit_symbols_still_win_over_portfolio(monkeypatch) -> None:
    _patch_offline(monkeypatch)
    _FakePortfolio.symbols = list(PORTFOLIO_SYMBOLS)
    _tldr_index(monkeypatch)
    routed = server._route_function_params("TLDR", {"symbols": ["MSFT", "AAPL"]})
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(**routed))
    assert result.data["watchlist"] == ["MSFT", "AAPL"]


def test_tldr_empty_portfolio_has_no_invented_watchlist(monkeypatch) -> None:
    """With no positions and no symbols the handler must not substitute a
    hard-coded list (AAPL/MSFT/TSLA/BTCUSDT/EURUSD/DGS10)."""
    _patch_offline(monkeypatch)
    _FakePortfolio.symbols = []
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute())
    assert result.data["watchlist"] == []
    assert result.data["status"] == "provider_unavailable"
