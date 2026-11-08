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


def _patch_news_calendar(monkeypatch, top, eco) -> None:
    """Replace TOP and ECO with canned results (or exceptions)."""
    import showme.engine.functions.macro.eco as eco_mod
    import showme.engine.functions.news.top as top_mod

    def _make(value):
        async def _execute(self, *args, **kwargs):
            if isinstance(value, Exception):
                raise value
            return value

        return _execute

    monkeypatch.setattr(top_mod.TOPFunction, "execute", _make(top))
    monkeypatch.setattr(eco_mod.ECOFunction, "execute", _make(eco))


def _top_ok():
    from showme.engine.core.base_function import FunctionResult

    return FunctionResult(
        code="TOP", instrument=None,
        data={"items": [{"title": "Fed holds rates"}, {"title": "Chip rally"}], "alerts": [], "status": "ok"},
        sources=["rss"],
    )


def _eco_ok():
    from showme.engine.core.base_function import FunctionResult

    events = [{"event": "CPI", "country": "US"}, {"event": "Payrolls", "country": "US"}]
    return FunctionResult(
        code="ECO", instrument=None,
        data={"status": "ok", "events": events, "rows": events, "surface": [], "cards": []},
        sources=["forex_factory"],
    )


def test_tldr_dict_payloads_are_read_not_sliced(monkeypatch) -> None:
    """TLDR#3: TOP and ECO return dict envelopes; TLDR must read their rows
    instead of slicing the dict (which raised KeyError and emptied both lists)."""
    _patch_offline(monkeypatch)
    _patch_news_calendar(monkeypatch, _top_ok(), _eco_ok())
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(symbols=["MSFT"]))
    assert not [w for w in result.warnings if "slice" in w], result.warnings
    assert result.data["news"] == ["Fed holds rates", "Chip rally"]
    assert len(result.data["events"]) == 2
    markdown = result.data["markdown"]
    assert "Calendar items:** 2 scheduled" in markdown
    assert "Fed holds rates" in markdown


def test_tldr_failed_calendar_is_unavailable_not_zero(monkeypatch) -> None:
    """TLDR#3: a failed calendar call must not be reported as '0 scheduled'."""
    _patch_offline(monkeypatch)
    _patch_news_calendar(monkeypatch, _top_ok(), RuntimeError("eco timeout"))
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(symbols=["MSFT"]))
    markdown = result.data["markdown"]
    assert "0 scheduled" not in markdown
    assert "Calendar items:** unavailable" in markdown
    assert result.data["calendar_status"] == "unavailable"


def test_tldr_unavailable_news_is_labelled_not_blank(monkeypatch) -> None:
    from showme.engine.core.base_function import FunctionResult

    _patch_offline(monkeypatch)
    top_down = FunctionResult(
        code="TOP", instrument=None,
        data={"items": [], "alerts": [], "status": "provider_unavailable", "reason": "rss down"},
        sources=[],
    )
    _patch_news_calendar(monkeypatch, top_down, _eco_ok())
    result = asyncio.run(TLDRFunction(deps=FunctionDeps()).execute(symbols=["MSFT"]))
    assert result.data["news_status"] == "unavailable"
    assert "**News themes:** unavailable" in result.data["markdown"]
