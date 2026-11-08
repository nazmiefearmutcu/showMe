"""AV SEC rows are labelled as the filings they are (AV#1).

Every SEC EDGAR row used to be typed ``media_type="earnings_call"`` (or
"conference") and flagged ``has_transcript=True`` because a primary HTML
document existed. The pane then counted them as "With transcript". A 10-K or an
8-K is a filing document, not an earnings-call recording or a transcript, so
the row must say ``filing`` and ``has_transcript`` must be False (no transcript
store is wired). Network is patched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import av as av_mod
from showme.engine.functions.news.av import AVFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _submissions():
    today = datetime.now(timezone.utc).date()
    d = lambda n: (today - timedelta(days=n)).isoformat()  # noqa: E731
    return {
        "filings": {
            "recent": {
                "form": ["10-K", "8-K", "DEF 14A"],
                "filingDate": [d(3), d(20), d(40)],
                "reportDate": [d(9), d(25), ""],
                "accessionNumber": [
                    "0000320193-26-000026",
                    "0000320193-26-000020",
                    "0000320193-26-000005",
                ],
                "primaryDocument": ["aapl-10k.htm", "aapl-8k.htm", "def14a.htm"],
                "primaryDocDescription": ["10-K", "8-K", "DEF 14A"],
                "items": ["", "2.02,9.01", ""],
            }
        }
    }


def _run_sec(monkeypatch):
    fn = AVFunction()

    async def _cik(symbol, params):
        return 320193

    async def _get_json(url, headers, timeout):
        return _submissions()

    monkeypatch.setattr(fn, "_resolve_cik", _cik)
    monkeypatch.setattr(av_mod, "_get_json", _get_json)
    return asyncio.run(fn.execute(instrument=AAPL)).data


def test_sec_rows_are_filings_not_earnings_calls(monkeypatch):
    payload = _run_sec(monkeypatch)
    assert payload["status"] == "ok"
    rows = payload["rows"]
    assert len(rows) == 3
    for row in rows:
        # A filing document is not a call recording or a conference replay.
        assert row["media_type"] == "filing", row
        assert row["media_type"] not in {"earnings_call", "conference"}, row
        assert row["form"] in {"10-K", "8-K", "DEF 14A"}


def test_sec_rows_never_claim_a_transcript(monkeypatch):
    payload = _run_sec(monkeypatch)
    for row in payload["rows"]:
        assert row["has_transcript"] is False, row
    assert payload["cards"]["items_with_transcript"] == 0
