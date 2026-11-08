"""BRIEF section, URL and positions contracts (wc1-g30).

Offline: PortfolioState, saved watchlists, TOP and the sentiment stamper are
stubbed. TOP's ranked items carry ``link`` (not ``url``) exactly as the live
TOP output does.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.instrument import AssetClass
from showme.engine.functions.news import brief as brief_mod
from showme.engine.functions.news import top as top_mod


class _Position:
    def __init__(self, symbol, asset_class):
        from showme.engine.core.instrument import Instrument

        self.instrument = Instrument(symbol=symbol, asset_class=asset_class)


def _run(coro):
    return asyncio.run(coro)


def _item(tag: str, n: int) -> dict:
    return {
        "title": f"{tag} headline {n}",
        "link": f"https://news.example.com/{tag.lower()}/{n}",
        "source": "example.com",
        "feed": "rss",
        "published_at": "2026-11-08T09:00:00+00:00",
    }


@pytest.fixture
def stub(monkeypatch):
    state = {"positions": [], "watchlists": []}

    class _Portfolio:
        def __init__(self):
            self.positions = [_Position(s, ac) for s, ac in state["positions"]]

        def import_legacy_crypto(self):
            return None

    def _lists(user_id="local"):
        return list(state["watchlists"])

    async def _top_execute(self, **kwargs):
        if kwargs.get("symbol"):
            sym = kwargs["symbol"]
            items = [_item(sym, n) for n in range(3)]
        else:
            items = [_item("MACRO", n) for n in range(3)]
        return SimpleNamespace(data={"items": items}, sources=["rss"], metadata={})

    async def _stamp(items):
        return items, None

    monkeypatch.setattr(brief_mod, "PortfolioState", _Portfolio, raising=False)
    monkeypatch.setattr(brief_mod, "list_watchlists", _lists, raising=False)
    monkeypatch.setattr(top_mod.TOPFunction, "execute", _top_execute)
    monkeypatch.setattr("showme.finbert_analyzer.stamp_items", _stamp)
    return state


# ---- BRIEF#2 -----------------------------------------------------------------


def test_positions_card_counts_held_symbols_in_the_brief(stub):
    """Default path: the Positions card is the number of portfolio positions in the brief."""
    stub["positions"] = [
        ("AAPL", AssetClass.EQUITY),
        ("MSFT", AssetClass.EQUITY),
        ("NVDA", AssetClass.EQUITY),
        ("SPY", AssetClass.ETF),
        ("TLT", AssetClass.ETF),
        ("GLD", AssetClass.ETF),
        ("BTC-USD", AssetClass.CRYPTO),
    ]
    res = _run(brief_mod.BRIEFFunction(None).execute())
    cards = {c["key"]: c["value"] for c in res.data["cards"]}
    assert cards["watchlist_size"] == 7
    assert cards["positions_covered"] == 7


# ---- BRIEF#3 -----------------------------------------------------------------


def test_top_stories_are_not_starved_by_watchlist_headlines(stub):
    """A watchlist flood must not push every macro story out of a per-section limit."""
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL", "MSFT", "NVDA"], limit=6))
    sections = [a["section"] for a in res.data["articles"]]
    assert "top_stories" in sections, sections
    assert "watchlist" in sections, sections


def test_limit_applies_per_section(stub):
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL", "MSFT", "NVDA"], limit=2))
    by_section: dict[str, int] = {}
    for a in res.data["articles"]:
        by_section[a["section"]] = by_section.get(a["section"], 0) + 1
    assert by_section.get("watchlist", 0) <= 2
    assert by_section.get("top_stories", 0) <= 2
    assert by_section.get("top_stories", 0) == 2


def test_sections_input_selects_the_article_sections(stub):
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL"], sections=["top_stories"]))
    assert res.data["status"] == "ok"
    assert {a["section"] for a in res.data["articles"]} == {"top_stories"}
    assert "## Watchlist" not in res.data["markdown"]
    assert "## Top Stories" in res.data["markdown"]


def test_sections_without_any_article_section_is_an_input_error(stub):
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL"], sections=["calendar"]))
    assert res.data["status"] == "input_error"
    assert res.data["articles"] == []
    assert res.data["next_actions"]


def test_markdown_lists_each_section_under_its_own_heading(stub):
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL"], limit=6))
    md = res.data["markdown"]
    assert "## Watchlist" in md
    assert "## Top Stories" in md
    watch_part, _, top_part = md.partition("## Top Stories")
    assert "(AAPL)" in watch_part.split("## Watchlist", 1)[1]
    assert "(MACRO)" in top_part
    assert "(MACRO)" not in watch_part


# ---- BRIEF#5 -----------------------------------------------------------------


def test_articles_expose_the_evidence_url_documented_in_the_field_dictionary(stub):
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL"], limit=6))
    assert res.data["articles"], "fixture must produce articles"
    for art in res.data["articles"]:
        assert art.get("url"), art
        assert art["url"] == art["link"]
