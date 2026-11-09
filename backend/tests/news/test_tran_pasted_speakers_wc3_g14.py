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


# --------------------------------------------------------------------------- #
# TRAN#2-RQ: the label rule must not drop real explicit headers, and a one-word
# label followed by prose must not be minted as a speaker.
# --------------------------------------------------------------------------- #
def test_all_caps_initials_still_name_an_explicit_speaker() -> None:
    rows = _parse_transcript_text("AJ Brown -- Chief Executive Officer\n\nThank you all.\n")
    speakers = {r["speaker"] for r in rows if r["speaker"]}
    assert speakers == {"AJ Brown"}, rows
    assert {r["role"] for r in rows if r["speaker"] == "AJ Brown"} == {"CEO"}, rows


def test_explicit_dash_header_whose_body_opens_with_a_figure_still_names_speaker() -> None:
    rows = _parse_transcript_text("Tim Cook -- 3 points to cover today.\n")
    assert rows and rows[0]["speaker"] == "Tim Cook", rows
    assert rows[0]["utterance"] == "3 points to cover today.", rows


def test_single_word_label_followed_by_prose_is_not_a_speaker() -> None:
    rows = _parse_transcript_text("Guidance: strong demand continues into next year.\n")
    assert len(rows) == 1, rows
    assert rows[0]["speaker"] is None and rows[0]["role"] == "", rows


def test_single_word_colon_header_is_not_a_speaker_but_role_word_is() -> None:
    rows = _parse_transcript_text("Outlook: Strong demand continues.\n\nOperator: Please go ahead.\n")
    speakers = [r["speaker"] for r in rows]
    assert "Outlook" not in speakers, rows
    assert "Operator" in speakers, rows


# --------------------------------------------------------------------------- #
# TRAN#2-RQ (second pass): a colon line is never a trusted speaker header.
# Two-token table labels outside the statement-word denylist used to be minted
# as speakers ("Retail Sales: gains continue" -> speaker "Retail Sales").
# Only "--" / dash headers are trusted as written; a colon line names a speaker
# only when its label is a role word such as "Operator".
# --------------------------------------------------------------------------- #
def test_two_token_colon_labels_outside_denylist_are_not_speakers() -> None:
    text = (
        "Retail Sales: gains continue here today.\n\n"
        "Return Rate: 4 percent of units.\n\n"
        "Store Traffic: up year over year.\n"
    )
    rows = _parse_transcript_text(text)
    assert len(rows) == 3, rows
    assert all(r["speaker"] is None for r in rows), rows
    assert all(r["role"] == "" for r in rows), rows


def test_person_name_with_colon_is_not_trusted_as_a_speaker() -> None:
    rows = _parse_transcript_text("Tim Cook: Thank you all for joining today.\n")
    assert len(rows) == 1, rows
    assert rows[0]["speaker"] is None and rows[0]["role"] == "", rows


def test_colon_role_word_header_still_names_operator() -> None:
    rows = _parse_transcript_text("Operator: Please go ahead.\n")
    assert rows and rows[0]["speaker"] == "Operator", rows
    assert rows[0]["utterance"] == "Please go ahead.", rows


def test_dash_header_for_two_token_name_still_names_speaker() -> None:
    rows = _parse_transcript_text("Retail Sales -- Chief Financial Officer\n\nGains continue.\n")
    body = [r for r in rows if r["utterance"] == "Gains continue."]
    assert body and body[0]["speaker"] == "Retail Sales", rows
    assert body[0]["role"] == "CFO", rows
