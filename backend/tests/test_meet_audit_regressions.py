"""Independent adversarial checks from the 2026-09-20 MEET audit."""
import asyncio
from datetime import UTC, datetime, timedelta

import pytest

from showme.engine.functions.comm import meet
from showme.engine.services import world_events as we
from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.data_sources.news.rss_adapter import RSSAdapter


NOW = datetime(2026, 9, 20, 10, tzinfo=UTC)


@pytest.mark.parametrize("title", [
    "Two killed in massive Ukrainian drone attack on Moscow region",
    "Hundreds of drones target Moscow on last day of voting",
    "Saudi response to Houthi attacks",
    "Houthis claim attack on Saudi capital",
    "Group With Al Qaeda Links Claims Responsibility for Attack in Pakistan",
])
def test_armed_attacks_are_spot_geopolitics(title):
    row = we.world_rows([{"title": title}], now=NOW)[0]
    assert row["details"]["event_type"] == "geopolitics"
    assert row["impact"] == "high"
    assert row["spot"] is True


@pytest.mark.parametrize("title", [
    "Drone manufacturer reports a cyber attack on its website",
    "Drones photograph the new London park",
    "Bitcoin network withstands a cyber attack",
])
def test_nonmilitary_drone_and_cyber_copy_is_not_war(title):
    row = we.world_rows([{"title": title}], now=NOW)[0]
    assert row["spot"] is False


@pytest.mark.parametrize("title", [
    "US NFP payrolls beat forecasts as unemployment falls",
    "Nonfarm payrolls revised higher in employment update",
    "Initial jobless claims rise in latest report",
])
def test_employment_is_not_inflation(title):
    tags, _ = we.match_topics(title)
    assert "EMPLOYMENT" in tags
    assert "INFLATION" not in tags


def test_mixed_employment_and_inflation_keeps_both_topics():
    tags, _ = we.match_topics("US payrolls rise while CPI inflation slows")
    assert {"EMPLOYMENT", "INFLATION"} <= set(tags)


def test_country_filter_can_find_headline_after_sixtieth_row(monkeypatch):
    fn = meet.MEETFunction()
    monkeypatch.setattr(meet, "_utc_now", lambda: NOW)
    # The country gates added 2026-10-04 fill a followed country short of the
    # 20-events floor with live Google News rows; this audit pin is about the
    # country-filter/limit mechanics, so the gate leg is stubbed offline.
    async def _gate_off(*args, **kwargs):
        return [], {"gate": "country_rss", "fired": False, "rows_added": 0,
                    "notes": ["stubbed offline in this audit pin"]}

    monkeypatch.setattr(meet.cg, "google_news_articles", _gate_off)
    articles = [
        {"title": f"Federal Reserve rate decision {i}", "url": f"https://example.test/{i}",
         "published_at": (NOW - timedelta(minutes=i + 1)).isoformat()}
        for i in range(65)
    ] + [{"title": "TCMB rate decision in Turkey", "url": "https://example.test/tcmb",
          "published_at": (NOW - timedelta(hours=2)).isoformat()}]

    async def headlines(**kwargs):
        return articles, "rss", None

    monkeypatch.setattr(fn, "_world_headlines", headlines)
    result = asyncio.run(fn.execute(mode="wire", countries="TR", limit=10))
    assert [r["title"] for r in result.data["rows"]] == ["TCMB rate decision in Turkey"]
    assert result.data["data_quality"]["rows_capped_at_limit"] == 0


def test_final_limit_reports_actual_excluded_rows(monkeypatch):
    fn = meet.MEETFunction()
    monkeypatch.setattr(meet, "_utc_now", lambda: NOW)

    async def headlines(**kwargs):
        return [
            {"title": f"Federal Reserve rate decision {i}", "url": f"https://example.test/{i}",
             "published_at": (NOW - timedelta(minutes=i + 1)).isoformat()}
            for i in range(65)
        ], "rss", None

    monkeypatch.setattr(fn, "_world_headlines", headlines)
    result = asyncio.run(fn.execute(mode="wire", limit=10))
    assert len(result.data["rows"]) == 10
    assert result.data["data_quality"]["rows_capped_at_limit"] == 55


def test_followed_symbol_headlines_respect_selected_time_window(monkeypatch):
    fn = meet.MEETFunction()
    monkeypatch.setattr(meet, "_utc_now", lambda: NOW)

    async def headlines(**kwargs):
        return [], "rss", None

    async def symbol_articles(*args, **kwargs):
        # (articles, error) — the Awareness symbol-news contract.
        return [{"title": "Bitcoin ETF inflows", "url": "https://example.test/old",
                 "published_at": (NOW - timedelta(days=5)).isoformat()}], None

    monkeypatch.setattr(fn, "_world_headlines", headlines)
    monkeypatch.setattr(fn, "_symbol_articles", symbol_articles)
    result = asyncio.run(fn.execute(mode="wire", symbols="BTC", days_back=1))
    assert result.data["rows"] == []
    assert result.data["symbol_rows"] == []


def test_dedicated_symbol_fetch_does_not_repeat_all_market_feeds():
    adapter = RSSAdapter()
    feeds = adapter._feeds_for(DataRequest(kind=DataKind.NEWS,
        extra={"feed_group": "market", "symbol": "TSLA", "symbol_only": True}))
    assert len(feeds) == 1
    assert "symbol=TSLA" in feeds[0]


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
