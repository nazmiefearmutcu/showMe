"""AV applies its date window (AV#2).

The manifest defaults ``date_range`` to ``last_90d`` and says an empty window
means the last 90 days, but the handler never read it, so filings and episodes
from more than a year back were returned as if they were the recent archive.
Network is patched; dates are relative to today so the tests stay valid.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import av as av_mod
from showme.engine.functions.news.av import AVFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _today():
    return datetime.now(timezone.utc).date()


def _sec_recent(days_ago_list):
    today = _today()
    dates = [(today - timedelta(days=n)).isoformat() for n in days_ago_list]
    n = len(dates)
    return {
        "form": ["8-K"] * n,
        "filingDate": dates,
        "reportDate": [""] * n,
        "accessionNumber": [f"0000320193-26-{i:06d}" for i in range(n)],
        "primaryDocument": ["a8k.htm"] * n,
        "primaryDocDescription": ["8-K"] * n,
        "items": ["2.02"] * n,
    }


def _run_sec(monkeypatch, days_ago_list, **params):
    fn = AVFunction()

    async def _cik(symbol, p):
        return 320193

    async def _get_json(url, headers, timeout):
        return {"filings": {"recent": _sec_recent(days_ago_list)}}

    monkeypatch.setattr(fn, "_resolve_cik", _cik)
    monkeypatch.setattr(av_mod, "_get_json", _get_json)
    return asyncio.run(fn.execute(instrument=AAPL, **params)).data


def test_default_window_drops_filings_older_than_90_days(monkeypatch):
    payload = _run_sec(monkeypatch, [10, 60, 200, 400])
    assert payload["status"] == "ok"
    dates = [r["event_date"] for r in payload["rows"]]
    assert len(dates) == 2, dates
    cutoff = (_today() - timedelta(days=90)).isoformat()
    assert all(d >= cutoff for d in dates), (dates, cutoff)
    assert payload["date_range"] == "last_90d"


def test_explicit_window_is_honoured(monkeypatch):
    payload = _run_sec(monkeypatch, [10, 60, 200], date_range="last_30d")
    dates = [r["event_date"] for r in payload["rows"]]
    assert len(dates) == 1, dates


def test_all_disables_the_window(monkeypatch):
    payload = _run_sec(monkeypatch, [10, 200, 400], date_range="all")
    assert len(payload["rows"]) == 3


def test_unsupported_window_is_an_input_error(monkeypatch):
    payload = _run_sec(monkeypatch, [10], date_range="last_banana")
    assert payload["status"] == "input_error"
    assert payload["rows"] == []
    assert "date_range" in payload["reason"]


def test_window_with_no_filings_is_empty_not_unavailable(monkeypatch):
    payload = _run_sec(monkeypatch, [400, 500])
    assert payload["status"] == "empty"
    assert payload["rows"] == []
    assert "90 days" in payload["reason"]


class _FakeResp:
    def __init__(self, text):
        self.text = text
        self.status_code = 200


class _FakeClient:
    def __init__(self, *a, **k):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url):
        return _FakeResp(_rss())


def _rss():
    today = datetime.now(timezone.utc)
    recent = format_datetime(today - timedelta(days=5))
    old = format_datetime(today - timedelta(days=400))
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Planet Money</title>
<item><title>Recent episode</title><link>https://example.com/recent</link>
<pubDate>{recent}</pubDate>
<enclosure url="https://example.com/recent.mp3" type="audio/mpeg" length="1"/></item>
<item><title>Old episode</title><link>https://example.com/old</link>
<pubDate>{old}</pubDate>
<enclosure url="https://example.com/old.mp3" type="audio/mpeg" length="1"/></item>
</channel></rss>"""


def test_podcast_default_window_drops_old_episodes(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    result = asyncio.run(AVFunction().execute(instrument=None))
    titles = [r["title"] for r in result.data["rows"]]
    assert "Recent episode" in titles
    assert "Old episode" not in titles


@pytest.mark.parametrize("value,expected", [
    ("2026-11-01", True),
    ("Wed, 19 Aug 2026 09:00:00 GMT", True),
    ("", False),
    (None, False),
    ("not a date", False),
])
def test_parse_event_date(value, expected):
    assert (av_mod._parse_event_date(value) is not None) is expected
