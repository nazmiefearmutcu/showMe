"""Regression tests for TRAN findings TRAN#1 (press release shown as a call
transcript) and TRAN#2 (speakers and roles invented by the parser).

The SEC fetch and the local transcript archive are patched, so no network is used.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import tran as tran_mod
from showme.engine.functions.news.tran import TRANFunction, _parse_transcript_text

# Shape of an 8-K EX-99.1 earnings release: no speaker headers, table labels,
# and a boilerplate note. Blocks are separated by blank lines as the cleaner emits them.
PRESS_RELEASE = """\
Apple reports fourth quarter results

CUPERTINO, California, Apple today announced financial results for its fiscal 2026 fourth quarter.

"Our September quarter revenue was driven by iPhone," said Tim Cook, Apple's CEO.

"Gross margin came in above our guidance," said Kevan Parekh, Apple's CFO.

Operating expenses: 15,000

Non-current liabilities: 99,000

Non-current assets: 88,000

NOTE TO EDITORS: This release is provided for information purposes only.
"""

_SAMPLE_TRANSCRIPT = """\
Operator -- Conference Coordinator

Good day, and welcome to the earnings conference call.

Tim Cook -- Chief Executive Officer

Thank you. Revenue was a record for the September quarter.

Luca Maestri -- Chief Financial Officer

Gross margin came in above the high end of our guidance.
"""


def _instrument(symbol: str = "AAPL") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


def _patch_sec_release(monkeypatch) -> None:
    async def _fake_sec(symbol, deps=None):  # noqa: ARG001
        meta = {
            "symbol": symbol,
            "form": "8-K",
            "accession": "0000320193-26-000024",
            "event_date": "2026-10-30",
            "filing_date": "2026-10-30",
            "quarter": "Q4 FY26",
            "source": "sec_edgar",
            "title": f"{symbol} 8-K earnings press release",
            "source_url": "https://www.sec.gov/Archives/edgar/data/320193/000032019326000024/",
        }
        return meta, PRESS_RELEASE

    from showme.engine.services import transcripts_archive as archive

    monkeypatch.setattr(tran_mod, "_fetch_sec_earnings_press_release", _fake_sec)
    monkeypatch.setattr(archive, "list_for_symbol", lambda *a, **k: [])


def _run_default(monkeypatch):
    _patch_sec_release(monkeypatch)
    return asyncio.run(TRANFunction().execute(_instrument()))


# ── TRAN#1 ─────────────────────────────────────────────────────────────────


def test_tran1_sec_default_path_is_labelled_as_press_release(monkeypatch) -> None:
    result = _run_default(monkeypatch)
    data = result.data
    assert data["status"] == "ok"
    assert "sec_edgar" in result.sources
    # The document type must say this is the release, not a call transcript.
    assert data["document_type"] == "earnings_press_release"
    # The event title is passed through from the 8-K metadata unchanged; it must
    # not be replaced by a transcript title.
    assert data["event"]["title"] == "AAPL 8-K earnings press release"
    assert data["data_mode"] == "live_official"
    assert any("not an earnings call transcript" in w for w in result.warnings)


def test_tran1_pasted_transcript_stays_a_transcript(monkeypatch) -> None:
    """Regression guard: user-supplied transcripts keep the transcript label."""

    async def _unused(*a, **k):  # pragma: no cover - must not be reached
        raise AssertionError("SEC path must not run when transcript_text is given")

    monkeypatch.setattr(tran_mod, "_fetch_sec_earnings_press_release", _unused)
    result = asyncio.run(
        TRANFunction().execute(_instrument(), transcript_text=_SAMPLE_TRANSCRIPT)
    )
    assert result.data["status"] == "ok"
    assert result.data["document_type"] == "transcript"


# ── TRAN#2 ─────────────────────────────────────────────────────────────────


def test_tran2_press_release_has_no_invented_speakers(monkeypatch) -> None:
    result = _run_default(monkeypatch)
    rows = result.data["utterances"]
    assert rows, "press release text must still be shown"
    speakers = {r["speaker"] for r in rows if r.get("speaker")}
    # Table labels and boilerplate must never become speakers, and the
    # "Management" default must never be attributed to unheaded text.
    assert "Management" not in speakers
    assert "Operating expenses" not in speakers
    assert "Non-current liabilities" not in speakers
    assert "NOTE TO EDITORS" not in speakers
    # No explicit speaker header exists in a press release.
    assert all(not r.get("speaker") for r in rows)
    assert all(r.get("role") == "" for r in rows)
    assert all(r["section"] == "document" for r in rows)


def test_tran2_release_text_never_mints_speakers_from_labels(monkeypatch) -> None:
    """Release text has no headers by definition, so header parsing is skipped.

    Labels outside the _NON_NAME_TOKENS denylist ("Accounts Receivable",
    "Apple Services --") must not become speakers when the source is a release.
    """
    release = (
        "Apple reports results\n\n"
        "Accounts Receivable: 1,000\n\n"
        "Apple Services -- strong quarter for subscriptions\n\n"
        "Accounts Payable: 2,000\n"
    )

    async def _fake_sec(symbol, deps=None):  # noqa: ARG001
        return {"symbol": symbol, "form": "8-K", "source": "sec_edgar"}, release

    from showme.engine.services import transcripts_archive as archive

    monkeypatch.setattr(tran_mod, "_fetch_sec_earnings_press_release", _fake_sec)
    monkeypatch.setattr(archive, "list_for_symbol", lambda *a, **k: [])
    result = asyncio.run(TRANFunction().execute(_instrument()))
    rows = result.data["utterances"]
    assert rows
    assert all(not r.get("speaker") for r in rows)
    assert all(r.get("role") == "" for r in rows)
    assert all(r["section"] == "document" for r in rows)


def test_tran2_parser_without_header_mode_attributes_nobody() -> None:
    text = "Accounts Receivable: 1,000\n\nApple Services -- strong quarter\n"
    rows = _parse_transcript_text(text, default_section="document", allow_speaker_headers=False)
    assert rows
    assert all(r["speaker"] is None for r in rows)
    assert all(r["section"] == "document" for r in rows)


def test_tran2_transcript_headers_still_attribute_speakers_and_roles() -> None:
    rows = _parse_transcript_text(_SAMPLE_TRANSCRIPT)
    by_speaker = {}
    for r in rows:
        by_speaker.setdefault(r["speaker"], r)
    assert by_speaker["Tim Cook"]["role"] == "CEO"
    assert by_speaker["Luca Maestri"]["role"] == "CFO"
    assert "Operator" in by_speaker
    assert "Management" not in by_speaker


def test_tran2_role_keyword_in_unheaded_text_is_not_attributed() -> None:
    """A role word in body text is not a speaker and must not mint a role."""
    rows = _parse_transcript_text("The CFO said margins improved this quarter.")
    assert len(rows) == 1
    assert rows[0]["speaker"] in (None, "")
    assert rows[0]["role"] == ""


def test_tran2_single_name_speaker_header_is_still_attributed() -> None:
    """Regression: a one-token speaker header ("Tim -- CEO") must keep its speaker.

    The release-path fix (no header parsing for press releases) must not
    stop transcript headers with a single name from attributing remarks.
    """
    rows = _parse_transcript_text("Tim -- CEO\n\nRevenue was a record.\n")
    body = [r for r in rows if r["utterance"] == "Revenue was a record."]
    assert body, "body paragraph must be kept"
    assert body[0]["speaker"] == "Tim"
    assert body[0]["role"] == "CEO"


def test_tran2_single_table_label_header_still_mints_no_speaker() -> None:
    """A one-token statement word ("Revenue: 1,000") is still not a speaker."""
    rows = _parse_transcript_text("Revenue: 1,000\n\nOperating expenses: 15,000\n")
    assert rows
    assert all(r["speaker"] is None for r in rows)
