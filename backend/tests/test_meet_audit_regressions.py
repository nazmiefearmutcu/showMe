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


def test_financecalendar_requests_full_documented_window(monkeypatch):
    monkeypatch.setitem(meet._FINANCE_CALENDAR_CACHE, "fetched_at", 0)
    requests = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"events": []}

    class Client:
        async def get(self, url, **kwargs):
            requests.append(kwargs["params"])
            return Response()

    asyncio.run(meet._finance_calendar_events(client=Client(), now=NOW, days_ahead=90, timeout=2))
    assert requests[0]["limit"] == 500
    assert requests[0]["to"] == (NOW + timedelta(days=90)).date().isoformat()


@pytest.mark.parametrize("ahead", [90, 180, 365])
def test_financecalendar_includes_history_without_shortening_future(monkeypatch, ahead):
    monkeypatch.setitem(meet._FINANCE_CALENDAR_CACHE, "fetched_at", 0)
    requests = []

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"events": []}

    class Client:
        async def get(self, url, **kwargs):
            requests.append(kwargs["params"])
            return Response()

    asyncio.run(meet._finance_calendar_events(
        client=Client(), now=NOW, days_ahead=ahead, days_back=7, timeout=2))
    assert requests[0]["from"] == "2026-09-13"
    assert requests[-1]["to"] == (NOW + timedelta(days=ahead)).date().isoformat()
    assert all((datetime.fromisoformat(r["to"]) - datetime.fromisoformat(r["from"])).days < 92 for r in requests)


def test_beige_book_has_auditable_us_country_inference():
    rows = meet._normalize_calendar_rows({"events": [{"title": "Beige Book October 2026",
        "time_utc": "2026-10-14T18:00:00Z"}]}, "financecalendar")
    assert rows[0]["country"] == "US"
    assert rows[0]["country_basis"] == "title_inference"


def test_followed_symbol_headlines_respect_selected_time_window(monkeypatch):
    fn = meet.MEETFunction()
    monkeypatch.setattr(meet, "_utc_now", lambda: NOW)

    async def headlines(**kwargs):
        return [], "rss", None

    async def symbol_articles(*args, **kwargs):
        return [{"title": "Bitcoin ETF inflows", "url": "https://example.test/old",
                 "published_at": (NOW - timedelta(days=5)).isoformat()}]

    monkeypatch.setattr(fn, "_world_headlines", headlines)
    monkeypatch.setattr(fn, "_symbol_articles", symbol_articles)
    result = asyncio.run(fn.execute(mode="wire", symbols="BTC", days_back=1))
    assert result.data["rows"] == []
    assert result.data["symbol_rows"] == []


def test_every_followed_symbol_gets_its_own_feed(monkeypatch):
    monkeypatch.setattr(meet, "_SYMBOL_NEWS_CACHE", None)
    requested = []

    class RSS:
        async def fetch(self, request):
            requested.append(request.extra)
            return []

    fn = meet.MEETFunction(FunctionDeps(rss=RSS()))
    asyncio.run(fn._symbol_articles(["AAPL", "MSFT", "NVDA", "TSLA"], now=NOW, timeout=2))
    assert {r["symbol"] for r in requested} == {"AAPL", "MSFT", "NVDA", "TSLA"}
    assert all(r["symbol_only"] for r in requested)


def test_dedicated_symbol_fetch_does_not_repeat_all_market_feeds():
    adapter = RSSAdapter()
    feeds = adapter._feeds_for(DataRequest(kind=DataKind.NEWS,
        extra={"feed_group": "market", "symbol": "TSLA", "symbol_only": True}))
    assert len(feeds) == 1
    assert "symbol=TSLA" in feeds[0]


def test_failed_calendar_chunk_keeps_other_windows_and_exposes_error(monkeypatch):
    monkeypatch.setitem(meet._FINANCE_CALENDAR_CACHE, "fetched_at", 0)

    class Response:
        def raise_for_status(self):
            pass

        def json(self):
            return {"events": [{"title": "US CPI", "time_utc": "2026-09-21T12:30:00Z"}]}

    class Client:
        async def get(self, url, **kwargs):
            if kwargs["params"]["from"] > NOW.date().isoformat():
                raise RuntimeError("upstream unavailable")
            return Response()

    rows, _, error = asyncio.run(meet._finance_calendar_events(
        client=Client(), now=NOW, days_ahead=180, timeout=2))
    assert [row["event"] for row in rows] == ["US CPI"]
    assert "upstream unavailable" in error
    assert meet._FINANCE_CALENDAR_CACHE["fetched_at"] == 0
