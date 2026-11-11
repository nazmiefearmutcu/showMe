"""MEET country gates — keyless per-country coverage floor (2026-10-04).

The shared calendar chain tags only ~10 major currencies, so followed
countries outside that set (TR, IN, BR, …) rendered an empty MEET pane.
These tests pin the three keyless gates added in
``showme.engine.services.country_gates``:

  * holiday gate — Nager.Date rows normalize into the calendar schema,
    respect the requested window, cache per (country, year) and fall back
    to the Google public-holiday ICS for countries Nager does not cover;
  * country wire gate — GDELT queries are scoped to the followed country
    over the 7-day lookback and carry the item-level gdelt source;
  * country RSS gate — Google News feeds parse, TTL-cache, and fire only
    for countries still short of the 20-events-per-7-days floor;
  * MEET integration — gate rows reach the payload and the gate report +
    shortfalls ship alongside them.

Fully offline: every provider is a fake; no test performs network I/O.
"""

from __future__ import annotations

import pytest

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

_HERE = Path(__file__).resolve()
_BACKEND_DIR = _HERE.parents[1]
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

from showme.engine.functions.comm import meet as meet_mod
from showme.engine.services import country_gates as cg

_NOW = datetime(2026, 10, 4, 12, 0, 0, tzinfo=UTC)


class _FakeResponse:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        if self._json_data is None:
            raise ValueError("no json body")
        return self._json_data


class _RoutingClient:
    """httpx-like double: routes GET URLs to canned responses."""

    def __init__(self, routes: dict[str, _FakeResponse]):
        self._routes = routes
        self.calls: list[str] = []

    async def get(self, url, timeout=None, params=None, **kwargs):
        self.calls.append(str(url))
        for fragment, response in self._routes.items():
            if fragment in str(url):
                return response
        return _FakeResponse(status_code=404)


def _clear_caches():
    cg._HOLIDAY_CACHE.clear()
    cg._GOOGLE_NEWS_CACHE.clear()
    meet_mod._SYMBOL_NEWS_CACHE = None


# ---------------------------------------------------------------------------
# Holiday gate
# ---------------------------------------------------------------------------


def test_holiday_gate_rows_normalize_window_and_cache():
    _clear_caches()
    client = _RoutingClient({
        "date.nager.at": _FakeResponse(json_data=[
            {"date": "2026-10-29", "name": "Republic Day", "localName": "Cumhuriyet Bayrami"},
            {"date": "2026-01-01", "name": "New Year's Day"},
        ]),
    })

    async def run():
        return await cg.holiday_gate_rows(
            client, ["TR"], now=_NOW, days_back=7.0, days_ahead=90.0
        )

    rows, status = asyncio.run(run())
    assert status["gate"] == "holidays"
    assert status["rows_added"] == 1, "2026-01-01 is outside the 90d-ahead window"
    row = rows[0]
    assert row["country"] == "TR"
    assert row["provider"] == "nager_date"
    assert row["event"] == "Public Holiday: Republic Day"
    assert row["date"] == "2026-10-29T00:00:00Z"
    assert row["importance"] == "low"
    # Second call rides the 6 h cache: no new HTTP traffic.
    before = len(client.calls)
    rows2, status2 = asyncio.run(run())
    assert len(client.calls) == before
    assert status2["rows_added"] == 1
    assert [r["event"] for r in rows2] == [row["event"]]


def test_holiday_gate_google_ics_fallback_for_uncovered_country():
    _clear_caches()
    ics = "\n".join([
        "BEGIN:VCALENDAR",
        "BEGIN:VEVENT",
        "DTSTART;VALUE=DATE:20261002",
        "SUMMARY:Gandhi Jayanti",
        "END:VEVENT",
        "END:VCALENDAR",
    ])
    client = _RoutingClient({
        "date.nager.at": _FakeResponse(status_code=404),
        "calendar.google.com": _FakeResponse(text=ics),
    })

    async def run():
        return await cg.holiday_gate_rows(
            client, ["IN"], now=_NOW, days_back=7.0, days_ahead=7.0
        )

    rows, status = asyncio.run(run())
    assert status["rows_added"] == 1
    assert rows[0]["provider"] == "google_holidays"
    assert rows[0]["event"] == "Public Holiday: Gandhi Jayanti"
    assert rows[0]["country"] == "IN"


def test_holiday_gate_failure_reported_never_raised():
    _clear_caches()
    client = _RoutingClient({
        "date.nager.at": _FakeResponse(status_code=500),
    })

    async def run():
        return await cg.holiday_gate_rows(
            client, ["TR"], now=_NOW, days_back=7.0, days_ahead=7.0
        )

    rows, status = asyncio.run(run())
    assert rows == []
    assert any("nager_date TR" in note for note in status["notes"])


# ---------------------------------------------------------------------------
# Country wire gate
# ---------------------------------------------------------------------------


class _RecordingGDELT:
    def __init__(self, articles):
        self._articles = articles
        self.queries: list[str] = []
        self.starts: list[object] = []

    async def search(self, query, *, start=None, max_records=50, **kwargs):
        self.queries.append(query)
        self.starts.append(start)
        return list(self._articles)


def test_country_wire_queries_are_country_scoped_over_7_days():
    _clear_caches()
    articles = [
        {"title": "Turkish inflation cools", "url": "https://example.test/tr-1",
         "seendate": "20261003T120000Z"},
    ]
    gdelt = _RecordingGDELT(articles)

    async def run():
        return await cg.country_wire_articles(
            gdelt, ["TR"], now=_NOW, lookback_days=7.0
        )

    got, status = asyncio.run(run())
    assert status["fired"] is True
    assert status["rows_added"] == 1
    assert status["countries"] == ["TR"]
    assert got and got[0]["source"] == "gdelt"
    assert gdelt.queries == ["turkey sourcelang:english"]
    start = gdelt.starts[0]
    assert (_NOW - start).days == 7, "7-day lookback window"


def test_country_wire_throttles_and_reports_failures():
    _clear_caches()

    class _Boom:
        async def search(self, query, **kwargs):
            raise RuntimeError("HTTP 429")

    got, status = asyncio.run(
        cg.country_wire_articles(_Boom(), ["TR"], now=_NOW)
    )
    assert got == []
    assert status["fired"] is False
    assert any("429" in n for n in status["notes"])


# ---------------------------------------------------------------------------
# Google News RSS gate
# ---------------------------------------------------------------------------


_GOOGLE_NEWS_XML = """<?xml version="1.0"?>
<rss version="2.0"><channel><title>Turkey - latest</title>
<item><title>Turkish central bank holds rates</title>
<link>https://example.test/tr-cb</link>
<pubDate>Sat, 03 Oct 2026 10:00:00 GMT</pubDate>
<description>Rate held.</description></item>
<item><title>Second Turkey story</title>
<link>https://example.test/tr-2</link>
<pubDate>Sat, 03 Oct 2026 09:00:00 GMT</pubDate>
</item>
</channel></rss>"""


def test_google_news_gate_parses_and_ttl_caches():
    _clear_caches()
    client = _RoutingClient({
        "news.google.com": _FakeResponse(text=_GOOGLE_NEWS_XML),
    })

    async def run():
        return await cg.google_news_articles(client, ["TR"])

    articles, status = asyncio.run(run())
    assert status["fired"] is True
    assert len(articles) == 2
    assert articles[0]["title"] == "Turkish central bank holds rates"
    assert articles[0]["published_at"], "pubDate parsed into published_at"
    before = len(client.calls)
    articles2, _ = asyncio.run(run())
    assert len(client.calls) == before, "second pass rides the TTL cache"
    assert len(articles2) == 2


# ---------------------------------------------------------------------------
# Floor accounting
# ---------------------------------------------------------------------------


def test_gate_window_counts_and_shortfall_warnings():
    rows = [
        {"countries": ["TR"], "seconds_to_event": -3600.0},          # past 7d
        {"countries": ["TR"], "seconds_to_event": 3600.0},           # future 7d
        {"countries": ["TR"], "seconds_to_event": 30 * 86400.0},     # outside 7d
        {"countries": ["US"], "seconds_to_event": -60.0},            # other country
    ]
    report = cg.gate_window_counts(rows, ["TR"], now=_NOW)
    assert report == [{
        "iso": "TR", "name": "Turkey",
        "past_7d": 1, "future_7d": 1,
        "past_met": False, "future_met": False,
    }]
    warnings = cg.shortfall_warnings(report)
    assert len(warnings) == 2
    assert "TR past 7d has 1/20" in warnings[0]
    assert "TR future 7d has 1/20" in warnings[1]


# ---------------------------------------------------------------------------
# MEET integration
# ---------------------------------------------------------------------------


class _WorldGDELT:
    """Answers the shared world query with one dated article."""

    async def search(self, query, **kwargs):
        return [{
            "title": "Markets watch global inflation data",
            "url": "https://example.test/world-1",
            "seendate": "20261003T110000Z",
        }]


class _InstantRSS:
    async def fetch(self, request):
        return []


@pytest.fixture(autouse=True)
def _awareness_offline(monkeypatch):
    """Tests never hit the live awareness-markets service; injected fakes still win."""
    from showme.engine.data_sources.awareness import AwarenessUnavailable
    from showme.engine.functions.calendar import _common as _aw_common

    class _Offline:
        async def get(self, path, params=None):
            raise AwarenessUnavailable("awareness disabled in tests")

    monkeypatch.setattr(_aw_common, "get_awareness_client", lambda: _Offline())
