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
    meet_mod._SYMBOL_NEWS_CACHE = None
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
        "rows_capped_at_limit": 0,
        "active_source_tiers": ["keyless_fallback", "future_supplement"],
        "measures": "observable_completeness_not_factual_accuracy",
    }


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


@pytest.mark.parametrize("title", [
    "Military coup in Myanmar as troops seize power",
    "NATO summit opens in Vilnius with Ukraine on agenda",
    "Putin declares martial law in border regions",
    "White House confirms nuclear test by North Korea",
    "Taiwan parliament passes sweeping defence bill",
    "Massive earthquake hits Tokyo, thousands feared dead",
])
def test_market_wire_recall_critical_patterns(title):
    assert rss_adapter._world_wire_relevant({"title": title}) is True


def test_market_wire_event_with_advice_pattern_still_kept():
    assert rss_adapter._world_wire_relevant(
        {"title": "Federal Reserve cuts rates: best stocks to buy now"}
    ) is True


def test_world_rows_limit_counts_capped_unique_rows():
    articles = [
        {"title": f"Federal Reserve rate decision update {i}",
         "url": f"https://x.test/cap/{i}",
         "published_at": NOW.isoformat()}
        for i in range(10)
    ]
    stats: dict[str, int] = {}
    rows = we.world_rows(articles, now=NOW, source="rss", limit=3, stats=stats)
    assert len(rows) == 3
    assert stats.get("rows_capped_at_limit") == 7
    assert stats.get("duplicate_rows_dropped", 0) == 0


def test_economic_id_dedupe_counts_duplicate():
    row = {"title": "CPI", "country": "USD", "date": NOW.isoformat(), "impact": "High"}
    stats: dict[str, int] = {}
    rows, _ = we.economic_rows([row, dict(row)], now=NOW, stats=stats)
    assert len(rows) == 1
    assert stats.get("duplicate_rows_dropped") == 1


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
