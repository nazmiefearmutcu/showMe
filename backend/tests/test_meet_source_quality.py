"""Task 3 source priority, provenance, and observable quality (offline)."""

from __future__ import annotations

import asyncio
import time
from datetime import UTC, datetime, timedelta

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.base_data_source import DataKind, DataRequest
from showme.engine.data_sources.news import rss_adapter
from showme.engine.functions.comm import meet as meet_mod
from showme.engine.functions.macro import eco as eco_mod
from showme.engine.services import world_events as we


NOW = datetime(2026, 9, 19, 18, 0, tzinfo=UTC)


class _Response:
    def __init__(self, payload):
        self.payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self.payload


class _CalendarHTTP:
    def __init__(self, *, ff=None, finance=None):
        self.ff = ff or []
        self.finance = finance or {"events": [], "attribution": {}}
        self.urls: list[str] = []

    async def get(self, url, timeout=None):
        self.urls.append(url)
        if "financecalendar.com" in url:
            return _Response(self.finance)
        return _Response(self.ff)


class _Provider:
    def __init__(self, rows, *, api_key="configured"):
        self.rows = rows
        self.api_key = api_key
        self.calls = 0

    async def calendar(self, **kwargs):
        self.calls += 1
        return self.rows

    async def economic_calendar(self, **kwargs):
        self.calls += 1
        return self.rows


class _StalledProvider(_Provider):
    async def calendar(self, **kwargs):
        self.calls += 1
        await asyncio.Event().wait()

    async def economic_calendar(self, **kwargs):
        self.calls += 1
        await asyncio.Event().wait()


@pytest.fixture(autouse=True)
def _reset_caches():
    meet_mod._WORLD_CACHE = None
    meet_mod._SYMBOL_NEWS_CACHE = None
    eco_mod._ff_cache["fetched_at"] = 0.0
    eco_mod._ff_cache["rows"] = []
    meet_mod._FINANCE_CALENDAR_CACHE["fetched_at"] = 0.0
    meet_mod._FINANCE_CALENDAR_CACHE["rows"] = []
    meet_mod._FINANCE_CALENDAR_CACHE["attribution"] = None
    yield


def _event(title: str, hours: int = 3) -> dict:
    return {
        "Country": "United States",
        "Event": title,
        "Date": (NOW + timedelta(hours=hours)).isoformat(),
        "Importance": 3,
        "Actual": 0,
        "Forecast": "1.2%",
        "Previous": "1.1%",
        "Unit": "%",
    }


def test_provider_priority_uses_configured_tradingeconomics_and_skips_lower_tiers(monkeypatch):
    monkeypatch.setattr(meet_mod, "_utc_now", lambda: NOW)
    te = _Provider([_event("Primary release")])
    finnhub = _Provider([_event("Should not be called")])
    http = _CalendarHTTP()
    fn = meet_mod.MEETFunction(FunctionDeps(tradingeconomics=te, finnhub=finnhub))
    fn._http_client = http

    result = asyncio.run(fn.execute(mode="calendar", days_ahead=30))

    assert te.calls == 1
    assert finnhub.calls == 0
    assert "tradingeconomics" in result.sources
    assert "forex_factory" not in result.sources
    row = result.data["rows"][0]
    assert row["title"] == "Primary release"
    assert row["countries"] == ["US"]
    assert row["impact"] == "high"
    assert row["details"]["actual"] == 0
    assert row["details"]["provider"] == "tradingeconomics"


def test_guest_te_is_never_called_and_configured_finnhub_is_next(monkeypatch):
    monkeypatch.setattr(meet_mod, "_utc_now", lambda: NOW)
    te = _Provider([_event("Forbidden guest")], api_key="guest:guest")
    finnhub = _Provider([_event("Finnhub release")])
    fn = meet_mod.MEETFunction(FunctionDeps(tradingeconomics=te, finnhub=finnhub))
    fn._http_client = _CalendarHTTP()

    result = asyncio.run(fn.execute(mode="calendar"))

    assert te.calls == 0
    assert finnhub.calls == 1
    assert result.sources[0] == "finnhub"


def test_financecalendar_supplements_future_window_and_primary_overlap_wins(monkeypatch):
    monkeypatch.setattr(meet_mod, "_utc_now", lambda: NOW)
    same = _event("CPI release", hours=5)
    future = (NOW + timedelta(days=20)).isoformat()
    finance = {
        "events": [
            {
                "title": "CPI release",
                "time_utc": same["Date"],
                "country": "United States",
                "importance": 1,
                "actual": "wrong",
            },
            {
                "title": "Bank of Japan Interest Rate Decision",
                "time_utc": future,
                "importance": 3,
                "forecast": None,
            },
        ],
        "attribution": {
            "name": "FinanceCalendar.com",
            "url": "https://www.financecalendar.com/",
            "text": "Economic calendar data by FinanceCalendar.com",
        },
    }
    te = _Provider([same])
    fn = meet_mod.MEETFunction(FunctionDeps(tradingeconomics=te))
    fn._http_client = _CalendarHTTP(finance=finance)

    result = asyncio.run(fn.execute(mode="calendar", days_ahead=30))

    rows = result.data["rows"]
    assert [r["title"] for r in rows].count("CPI release") == 1
    cpi = next(r for r in rows if r["title"] == "CPI release")
    assert cpi["source"] == "tradingeconomics"
    assert cpi["details"]["actual"] == 0
    boj = next(r for r in rows if "Japan" in r["title"])
    assert boj["source"] == "financecalendar"
    assert boj["countries"] == ["JP"]
    assert boj["details"]["country_basis"] == "title_inference"
    assert result.data["attributions"][0]["url"] == "https://www.financecalendar.com/"
    assert result.data["data_quality"]["duplicate_rows_dropped"] == 1


def test_rss_missing_timestamp_remains_undated_with_feed_and_url_provenance():
    xml = """<rss><channel><title>Example Wire</title><item>
      <title>Markets await central bank</title>
      <link>https://example.test/story</link>
      <description>Preview</description>
    </item></channel></rss>"""
    parsed = rss_adapter._parse_feed_stdlib(xml, "https://example.test/feed.xml")
    assert parsed[0]["published_at"] is None
    rows = we.world_rows(parsed, now=NOW, source="rss")
    assert rows[0]["undated"] is True
    assert rows[0]["when_utc"] is None
    assert rows[0]["details"]["publisher"] == "Example Wire"
    assert rows[0]["details"]["feed_url"] == "https://example.test/feed.xml"
    assert rows[0]["details"]["article_url"] == "https://example.test/story"


def test_quality_metrics_are_observable_counts_not_accuracy_claims():
    rows = [
        {"id": "1", "when_utc": NOW.isoformat(), "source": "forex_factory", "details": {"provider": "forex_factory"}},
        {"id": "2", "when_utc": None, "undated": True, "source": "rss", "details": {"publisher": "Wire", "article_url": "https://x.test/2"}},
        {"id": "3", "when_utc": NOW.isoformat(), "source": "financecalendar", "details": {"provider": "financecalendar"}},
    ]
    quality = meet_mod._data_quality(
        rows,
        duplicate_rows_dropped=2,
        dropped_no_time=1,
        active_source_tiers=["keyless_fallback", "future_supplement"],
        attributions=[{"name": "FinanceCalendar.com", "url": "https://www.financecalendar.com/"}],
    )
    assert quality == {
        "row_count": 3,
        "timed_count": 2,
        "undated_count": 1,
        "source_traceable_count": 3,
        "url_traceable_count": 1,
        "attribution_required_count": 1,
        "attribution_covered_count": 1,
        "duplicate_rows_dropped": 2,
        "rows_dropped_no_time": 1,
        "active_source_tiers": ["keyless_fallback", "future_supplement"],
        "measures": "observable_completeness_not_factual_accuracy",
    }


def test_wire_mode_skips_hidden_calendar_and_reports_news_failure(monkeypatch):
    monkeypatch.setattr(meet_mod, "_utc_now", lambda: NOW)
    te = _Provider([_event("Hidden release")])
    http = _CalendarHTTP(finance={"events": [_event("Hidden supplement")], "attribution": {}})
    fn = meet_mod.MEETFunction(FunctionDeps(tradingeconomics=te))
    fn._http_client = http
    result = asyncio.run(fn.execute(mode="wire"))
    assert te.calls == 0
    assert http.urls == []
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.sources == ["no_live_source"]
    assert result.data["data_quality"]["active_source_tiers"] == []


def test_stalled_keyed_providers_leave_budget_for_forex_factory(monkeypatch):
    monkeypatch.setattr(meet_mod, "_utc_now", lambda: NOW)
    te = _StalledProvider([])
    finnhub = _StalledProvider([])
    ff = [{"title": "CPI", "country": "USD", "date": (NOW + timedelta(hours=2)).isoformat(), "impact": "High"}]
    fn = meet_mod.MEETFunction(FunctionDeps(tradingeconomics=te, finnhub=finnhub))
    fn._http_client = _CalendarHTTP(ff=ff)
    started = time.monotonic()
    result = asyncio.run(fn.execute(mode="calendar", news_timeout=3))
    assert time.monotonic() - started < 4
    assert result.data["status"] == "ok"
    assert "forex_factory" in result.sources
    assert te.calls == finnhub.calls == 1


def test_untimed_high_priority_response_falls_through_and_counts_drop(monkeypatch):
    monkeypatch.setattr(meet_mod, "_utc_now", lambda: NOW)
    te = _Provider([{"Event": "Bad date", "Date": "nonsense", "Country": "US"}])
    finnhub = _Provider([_event("Valid fallback")])
    fn = meet_mod.MEETFunction(FunctionDeps(tradingeconomics=te, finnhub=finnhub))
    fn._http_client = _CalendarHTTP()
    result = asyncio.run(fn.execute(mode="calendar"))
    assert result.sources[0] == "finnhub"
    assert [r["title"] for r in result.data["rows"]] == ["Valid fallback"]
    assert result.data["dropped_no_time"] >= 1
    assert any("tradingeconomics" in warning and "untimed" in warning for warning in result.warnings)


def test_wire_url_overlap_deduped_and_tier_counted(monkeypatch):
    monkeypatch.setattr(meet_mod, "_utc_now", lambda: NOW)
    articles = [
        {"title": "Federal Reserve rate decision", "url": "https://example.test/one", "published_at": NOW.isoformat()},
        {"title": "Fed rate decision update", "url": "https://example.test/one", "published_at": NOW.isoformat()},
    ]
    async def headlines(*, now, timeout):
        return articles, "rss", None
    fn = meet_mod.MEETFunction()
    monkeypatch.setattr(fn, "_world_headlines", headlines)
    result = asyncio.run(fn.execute(mode="wire"))
    assert len(result.data["rows"]) == 1
    assert result.data["data_quality"]["duplicate_rows_dropped"] == 1
    assert result.data["data_quality"]["active_source_tiers"] == ["wire_rss_fallback"]


@pytest.mark.parametrize(("title", "iso"), [
    ("Riksbank Rate Decision September 2026", "SE"),
    ("Norges Bank Rate Decision September 2026", "NO"),
])
def test_conservative_central_bank_title_country_inference(title, iso):
    row = meet_mod._normalize_calendar_rows([{"title": title, "time_utc": NOW.isoformat()}], "financecalendar")[0]
    assert row["country"] == iso
    assert row["country_basis"] == "title_inference"


def test_default_market_rss_gate_removes_unrelated_copy_before_limit():
    articles = [
        {"title": "A guide to drinking wine in Paris", "link": "https://x.test/wine"},
        {"title": "New art book explores modern homes", "link": "https://x.test/book"},
        {"title": "Best stocks to buy for retirement", "link": "https://x.test/retirement"},
        {"title": "Federal Reserve rate decision moves bond yields", "link": "https://x.test/fed"},
        {"title": "Bitcoin ETF inflows jump after SEC approval", "link": "https://x.test/btc"},
    ]
    adapter = rss_adapter.RSSAdapter({"market_feeds": ["https://x.test/feed"]})
    async def collect(feeds, timeout_for):
        return [articles]
    adapter._collect_feeds = collect
    result = asyncio.run(adapter.fetch(DataRequest(kind=DataKind.NEWS, extra={"feed_group": "market"}, limit=2)))
    assert [article["link"] for article in result] == ["https://x.test/fed", "https://x.test/btc"]


@pytest.mark.parametrize("title", [
    "Massive Update for Applied Materials Stock Investors!",
    "Down 86%, Is it Finally Time to Buy Rivian Stock?",
    "Is Pfizer an Excellent Dividend Stock to Buy?",
    "Applied Materials announces quarterly earnings call webcast",
    "Company declares quarterly dividend in press release",
])
def test_market_wire_rejects_advice_and_routine_pr(title):
    assert rss_adapter._world_wire_relevant({"title": title}) is False


@pytest.mark.parametrize("title", [
    "Russian drone hits Kyiv power grid",
    "Israel strikes Iran nuclear facility",
    "President resigns amid nationwide protests",
    "Applied Materials shares jump after earnings beat",
    "Federal Reserve cuts interest rates",
    "Bitcoin ETF inflows surge after SEC approval",
])
def test_market_wire_keeps_concrete_events(title):
    assert rss_adapter._world_wire_relevant({"title": title}) is True


@pytest.mark.parametrize(("title", "expected"), [
    ("US Treasury’s Bessent, China’s He to meet on Sunday at JPMorgan headquarters", True),
    ("UN Talks Offer a New Opening on Iran War", True),
    ("Fashion council CEO resigns after board review", False),
    ("Fashion council cuts annual gala budget", False),
    ("TechCorp lays off 5,000 workers after demand slump", True),
    ("Nvidia reports earnings beat as revenue surges", True),
    ("TechCorp announces quarterly earnings call webcast", False),
])
def test_market_wire_requires_material_context_and_event(title, expected):
    assert rss_adapter._world_wire_relevant({"title": title}) is expected


def test_symbol_limit_truncation_is_not_counted_as_duplicate(monkeypatch):
    monkeypatch.setattr(meet_mod, "_utc_now", lambda: NOW)
    fn = meet_mod.MEETFunction()
    async def headlines(*, now, timeout):
        return [], "", "news: unavailable"
    async def symbol_articles(symbols, *, now, timeout):
        return [
            {"title": f"Bitcoin market update {i}", "url": f"https://x.test/{i}",
             "published_at": NOW.isoformat()}
            for i in range(61)
        ]
    monkeypatch.setattr(fn, "_world_headlines", headlines)
    monkeypatch.setattr(fn, "_symbol_articles", symbol_articles)
    result = asyncio.run(fn.execute(mode="wire", symbols="BTC"))
    assert len(result.data["rows"]) == 60
    assert result.data["data_quality"]["duplicate_rows_dropped"] == 0
