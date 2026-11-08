"""TRAN#2 and TRAN#3 follow-ups on the user-pasted transcript path (offline).

TRAN#2: a "Label: value" table line in pasted text must not become a speaker. Only
an explicit speaker header may name a speaker; anything else gets speaker None.

TRAN#3: a pasted transcript with a requested quarter is not checked against any
filing, so the event must say the quarter is user-stated and unverified.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news.tran import TRANFunction, _parse_transcript_text


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _instrument() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


_TABLE_LINES = """\
Diluted EPS: 1.23 per share

Adjusted EBITDA: 35 billion

Guidance: 2 to 3 percent growth

Return on Capital: 18 percent
"""

_REAL_HEADERS = """\
Tim Cook -- Chief Executive Officer

Thank you. Revenue was a record this quarter.

Luca Maestri -- Chief Financial Officer

Gross margin came in above guidance.
"""


def test_table_labels_do_not_become_speakers() -> None:
    rows = _parse_transcript_text(_TABLE_LINES)
    assert rows, "the text still yields rows"
    speakers = {r["speaker"] for r in rows}
    assert speakers == {None}, speakers
    assert all(r["role"] == "" for r in rows), rows


def test_explicit_speaker_headers_still_name_speakers() -> None:
    rows = _parse_transcript_text(_REAL_HEADERS)
    speakers = {r["speaker"] for r in rows if r["speaker"]}
    assert speakers == {"Tim Cook", "Luca Maestri"}, speakers


def test_pasted_quarter_is_labelled_as_user_stated_not_verified() -> None:
    text = _REAL_HEADERS
    result = _run(TRANFunction().execute(_instrument(), transcript_text=text, quarter="Q3 FY26"))
    event = result.data["event"]
    assert event["quarter"] == "Q3 FY26", event
    basis = str(event.get("quarter_basis") or "").lower()
    assert "user" in basis and "not verified" in basis, event
