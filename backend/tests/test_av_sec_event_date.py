"""AV event_date is the filing timestamp, not the period end (AV#5).

The field dictionary and seed describe ``event_date`` as the filing or
recording timestamp. The handler used SEC ``reportDate`` (the fiscal period
end) first, so a 10-K filed on 2026-11-03 for the period ending 2026-09-26
showed 2026-09-26, and a DEF 14A could show a date later than its own filing.
The period end is kept under its own name. Network is patched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import av as av_mod
from showme.engine.functions.news.av import AVFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _run_sec(monkeypatch, recent):
    fn = AVFunction()

    async def _cik(symbol, params):
        return 320193

    async def _get_json(url, headers, timeout):
        return {"filings": {"recent": recent}}

    monkeypatch.setattr(fn, "_resolve_cik", _cik)
    monkeypatch.setattr(av_mod, "_get_json", _get_json)
    return asyncio.run(fn.execute(instrument=AAPL)).data


def test_event_date_is_filing_date_and_period_end_is_separate(monkeypatch):
    today = datetime.now(timezone.utc).date()
    filed = (today - timedelta(days=5)).isoformat()
    period_end = (today - timedelta(days=45)).isoformat()
    payload = _run_sec(
        monkeypatch,
        {
            "form": ["10-K"],
            "filingDate": [filed],
            "reportDate": [period_end],
            "accessionNumber": ["0000320193-26-000026"],
            "primaryDocument": ["aapl-10k.htm"],
            "primaryDocDescription": ["10-K"],
            "items": [""],
        },
    )
    assert payload["status"] == "ok"
    row = payload["rows"][0]
    assert row["event_date"] == filed, row
    assert row["filing_date"] == filed
    assert row["period_end"] == period_end


def test_def14a_row_is_dated_by_its_filing(monkeypatch):
    # DEF 14A has no reportDate; the filing date must still be the event date.
    today = datetime.now(timezone.utc).date()
    filed = (today - timedelta(days=30)).isoformat()
    payload = _run_sec(
        monkeypatch,
        {
            "form": ["DEF 14A"],
            "filingDate": [filed],
            "reportDate": [""],
            "accessionNumber": ["0000320193-26-000005"],
            "primaryDocument": ["def14a.htm"],
            "primaryDocDescription": ["DEF 14A"],
            "items": [""],
        },
    )
    row = payload["rows"][0]
    assert row["event_date"] == filed
    assert row["period_end"] == ""
