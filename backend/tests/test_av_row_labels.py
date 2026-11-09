"""AV row labels: media type and titles are honest (AV#7).

* Podcast rows carried the enclosure MIME type (audio/mpeg) as media_type while
  the manifest enumerates podcast. media_type is now "podcast"; the MIME type
  stays in enclosure_type.
* Podcast event_date was the raw RFC 2822 pubDate, which the pane cut to ten
  characters ("Wed, 19 Au"). event_date is now an ISO date.
* SEC titles repeated the form ("AAPL 10-K — 10-K") because the primary doc
  description equals the form. The duplicate is dropped.

Network is patched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import av as av_mod
from showme.engine.functions.news.av import AVFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


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
    pub = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)
    return f"""<?xml version="1.0"?>
<rss version="2.0"><channel><title>Planet Money</title>
<item><title>Yield curve episode</title><link>https://example.com/ep</link>
<pubDate>{format_datetime(pub)}</pubDate>
<enclosure url="https://example.com/ep.mp3" type="audio/mpeg" length="1"/>
<itunes:duration xmlns:itunes="http://www.itunes.com/dtds/podcast-1.0.dtd">22:05</itunes:duration>
</item></channel></rss>"""


def test_podcast_row_is_typed_podcast_with_iso_date(monkeypatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)
    # Keep the window wide so the fixed 2026-10-19 episode is in range.
    result = asyncio.run(AVFunction().execute(instrument=None, date_range="all"))
    rows = result.data["rows"]
    assert rows, result.data
    row = rows[0]
    assert row["media_type"] == "podcast", row
    assert row["enclosure_type"] == "audio/mpeg"
    assert row["event_date"] == "2026-10-19", row
    assert row["published"]  # raw RFC 2822 value is kept for reference


def _sec(monkeypatch, form, desc, items):
    fn = AVFunction()
    today = datetime.now(timezone.utc).date()
    d = (today - timedelta(days=2)).isoformat()

    async def _cik(symbol, params):
        return 320193

    async def _get_json(url, headers, timeout):
        return {
            "filings": {
                "recent": {
                    "form": [form],
                    "filingDate": [d],
                    "reportDate": [""],
                    "accessionNumber": ["0000320193-26-000026"],
                    "primaryDocument": ["doc.htm"],
                    "primaryDocDescription": [desc],
                    "items": [items],
                }
            }
        }

    monkeypatch.setattr(fn, "_resolve_cik", _cik)
    monkeypatch.setattr(av_mod, "_get_json", _get_json)
    return asyncio.run(fn.execute(instrument=AAPL)).data["rows"][0]


def test_sec_title_does_not_repeat_the_form(monkeypatch):
    row = _sec(monkeypatch, "10-K", "10-K", "")
    assert row["title"] == "AAPL 10-K", row["title"]


def test_sec_title_uses_items_when_description_is_just_the_form(monkeypatch):
    row = _sec(monkeypatch, "8-K", "8-K", "2.02,9.01")
    assert row["title"] == "AAPL 8-K — Items 2.02,9.01", row["title"]


def test_sec_title_keeps_a_real_description(monkeypatch):
    row = _sec(monkeypatch, "DEF 14A", "Definitive proxy statement", "")
    assert row["title"] == "AAPL DEF 14A — Definitive proxy statement", row["title"]
