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


def test_empty_brief_markdown_renders_only_the_requested_section(stub, monkeypatch):
    """With zero articles the markdown still honours ``sections`` (no unrequested heading)."""

    async def _empty_top(self, **kwargs):
        return SimpleNamespace(data={"items": []}, sources=["rss"], metadata={})

    monkeypatch.setattr(top_mod.TOPFunction, "execute", _empty_top)

    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL"], sections=["watchlist"]))
    assert res.data["status"] == "provider_unavailable"
    md = res.data["markdown"]
    assert "## Watchlist" in md
    assert "## Top Stories" not in md

    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL"], sections=["top_stories"]))
    md = res.data["markdown"]
    assert "## Top Stories" in md
    assert "## Watchlist" not in md


# ---- BRIEF#3 (review follow-up): declared sections must match what is composed --


def test_manifest_declares_only_the_sections_the_handler_composes():
    """The seed must not advertise sections that BRIEF silently skips."""
    from showme.manifest.seeds.brief_seed import brief

    manifest = brief
    spec = next(i for i in manifest.inputs if i.name == "sections")
    assert list(spec.options) == ["top_stories", "watchlist"]
    assert list(manifest.defaults["sections"]) == ["top_stories", "watchlist"]


def test_unimplemented_sections_are_reported_not_silently_dropped(stub):
    res = _run(
        brief_mod.BRIEFFunction(None).execute(
            watchlist=["AAPL"],
            sections=["top_stories", "positions", "calendar"],
        )
    )
    assert res.data["sections"] == ["top_stories"]
    assert res.data["unsupported_sections"] == ["positions", "calendar"]
    assert any("positions" in w and "calendar" in w for w in res.warnings), res.warnings


def test_default_sections_raise_no_unsupported_warning(stub):
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL"]))
    assert res.data["unsupported_sections"] == []
    assert not any("not implemented" in w for w in res.warnings), res.warnings


# ---- BRIEF#5 (review follow-up): RSS publisher, not the adapter tag, is the source label --


def test_rss_items_are_labelled_with_their_publisher_not_the_adapter_tag(stub, monkeypatch):
    async def _rss_top(self, **kwargs):
        item = {
            "title": "Reuters macro headline",
            "link": "https://news.example.com/reuters/1",
            "source": "rss",
            "publisher": "Reuters",
            "feed": "Reuters",
            "published_at": "2026-11-08T09:00:00+00:00",
        }
        return SimpleNamespace(data={"items": [item]}, sources=["rss"], metadata={})

    monkeypatch.setattr(top_mod.TOPFunction, "execute", _rss_top)
    res = _run(brief_mod.BRIEFFunction(None).execute(watchlist=["AAPL"], sections=["top_stories"]))
    art = res.data["articles"][0]
    assert art["source"] == "Reuters"
    assert "— Reuters" in res.data["markdown"]
    assert "— rss" not in res.data["markdown"]
