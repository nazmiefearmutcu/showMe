"""AV podcast path reports an empty result honestly (AV#6).

When the RSS feeds answer and parse but no episode survives the query or the
media_type filter, the result is an empty match, not a provider outage. Only
feeds that cannot be read at all may return status='provider_unavailable'.
Network is patched; no test reaches the network.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from email.utils import format_datetime

from showme.engine.functions.news.av import AVFunction


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


class _DownClient(_FakeClient):
    async def get(self, url):
        raise RuntimeError("network unreachable")


def _rss():
    pub = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Planet Money</title>
<item><title>Yield curve episode</title><link>https://example.com/ep</link>
<pubDate>{format_datetime(pub)}</pubDate>
<enclosure url="https://example.com/ep.mp3" type="audio/mpeg" length="1"/>
</item></channel></rss>"""


def _run(monkeypatch, client_cls, **params):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", client_cls)
    return asyncio.run(AVFunction().execute(instrument=None, **params)).data


def test_media_filter_that_excludes_every_podcast_is_empty_not_outage(monkeypatch):
    payload = _run(monkeypatch, _FakeClient, media_type=["filing"], date_range="all")
    assert payload["status"] == "empty", payload["status"]
    assert payload["rows"] == []
    assert payload["reason"]
    assert "unavailable" not in payload["reason"].lower()


def test_query_with_no_podcast_match_is_empty_not_outage(monkeypatch):
    payload = _run(monkeypatch, _FakeClient, query="zzqxnonexistentterm", date_range="all")
    assert payload["status"] == "empty", payload["status"]
    assert payload["rows"] == []


def test_unreadable_feeds_still_report_provider_unavailable(monkeypatch):
    payload = _run(monkeypatch, _DownClient, date_range="all")
    assert payload["status"] == "provider_unavailable", payload["status"]
    assert payload["rows"] == []
