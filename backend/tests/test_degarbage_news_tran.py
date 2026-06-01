"""De-garbage regression tests for TRAN (Earnings Call Transcripts).

TRAN used to return either ``status="provider_unavailable"`` (relying on the
inert key-gated SeekingAlpha adapter) or, behind an opt-in flag, a HARDCODED
synthetic "earnings call transcript template" with canned Operator/Management
lines. The default path now returns REAL transcript text:

  * a user-pasted ``transcript_text`` is parsed verbatim into utterances;
  * otherwise SEC EDGAR (keyless) supplies the latest 8-K earnings press
    release Exhibit 99.x text.

These tests exercise the deterministic offline parsing path (no network) and
make an opportunistic live SEC fetch that SKIPS cleanly when the network is
down, asserting the honest ``provider_unavailable`` shape instead of any
fabricated rows.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news.tran import (
    TRANFunction,
    _parse_transcript_text,
)


def _instrument(symbol: str = "AAPL", asset: AssetClass = AssetClass.EQUITY) -> Instrument:
    return Instrument(symbol=symbol, asset_class=asset)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


_SAMPLE_TRANSCRIPT = """\
Operator -- Conference Coordinator

Good day, and welcome to the Apple Q4 Fiscal Year 2025 earnings conference call.

Tim Cook -- Chief Executive Officer

Thank you. Today Apple is reporting revenue of $94.9 billion, an all-time record for the September quarter, driven by strong iPhone demand and Services growth.

Luca Maestri -- Chief Financial Officer

Gross margin came in at 46.2%, above the high end of our guidance, and we returned over $29 billion to shareholders during the quarter.

Question-and-Answer Session

Operator

Our first question comes from the line of an analyst.

Tim Cook -- Chief Executive Officer

We are very pleased with the momentum we are seeing across all of our product categories heading into the holiday season.
"""


# --------------------------------------------------------------------------- #
# Pure parser — deterministic, no network.
# --------------------------------------------------------------------------- #
def test_parse_transcript_text_extracts_real_speakers() -> None:
    rows = _parse_transcript_text(_SAMPLE_TRANSCRIPT)
    assert rows, "parser must yield utterances"
    speakers = {r["speaker"] for r in rows}
    # Real names parsed out of the headers, not canned placeholders.
    assert "Tim Cook" in speakers
    assert "Luca Maestri" in speakers
    # Role inference works off the title fragment.
    cook_rows = [r for r in rows if r["speaker"] == "Tim Cook"]
    assert any(r["role"] == "CEO" for r in cook_rows)
    # Real verbatim content is preserved.
    assert any("94.9 billion" in r["utterance"] for r in rows)
    # The Q&A marker flipped the section.
    assert any(r["section"] == "qa" for r in rows)
    # Every row has the contract fields.
    for r in rows:
        assert {"section", "speaker", "role", "utterance"} <= set(r)
        assert r["utterance"].strip()


def test_parse_does_not_emit_legacy_template_strings() -> None:
    rows = _parse_transcript_text(_SAMPLE_TRANSCRIPT)
    blob = " ".join(r["utterance"] for r in rows).lower()
    # The old hardcoded template language must not appear.
    assert "prepared remarks and q&a sections are available when" not in blob
    assert "placeholders are structured for downstream search" not in blob


# --------------------------------------------------------------------------- #
# Handler — user-supplied transcript path (fully offline, real rows).
# --------------------------------------------------------------------------- #
def test_user_supplied_transcript_returns_ok_real_rows() -> None:
    fn = TRANFunction()
    result = _run(fn.execute(_instrument(), transcript_text=_SAMPLE_TRANSCRIPT))
    payload = result.data
    assert payload["status"] == "ok"
    assert payload["data_mode"] == "user_supplied"
    assert "user_supplied" in result.sources
    assert payload["utterances"], "utterances must be non-empty"
    assert payload["rows"] == payload["utterances"]
    assert "methodology" in payload and payload["methodology"].strip()
    assert "field_dictionary" in payload and payload["field_dictionary"]
    assert payload["cards"]["utterance_count"] == len(payload["utterances"])
    # positions are 1-based and contiguous.
    positions = [r["position"] for r in payload["utterances"]]
    assert positions == list(range(1, len(positions) + 1))


def test_speaker_filter_applies() -> None:
    fn = TRANFunction()
    result = _run(
        fn.execute(
            _instrument(),
            transcript_text=_SAMPLE_TRANSCRIPT,
            speaker_filter=["Tim Cook"],
        )
    )
    payload = result.data
    assert payload["status"] == "ok"
    assert payload["utterances"], "filter should still leave Tim Cook rows"
    assert all(r["speaker"] == "Tim Cook" for r in payload["utterances"])


def test_section_filter_qa_only() -> None:
    fn = TRANFunction()
    result = _run(
        fn.execute(_instrument(), transcript_text=_SAMPLE_TRANSCRIPT, section="qa")
    )
    payload = result.data
    assert payload["status"] == "ok"
    assert payload["utterances"]
    assert all(r["section"] == "qa" for r in payload["utterances"])


# --------------------------------------------------------------------------- #
# Handler — live SEC EDGAR default path, with graceful offline fallback.
# --------------------------------------------------------------------------- #
def test_live_sec_default_path_or_graceful_unavailable() -> None:
    fn = TRANFunction()
    result = _run(fn.execute(_instrument("AAPL")))
    payload = result.data
    assert payload["status"] in {"ok", "empty", "provider_unavailable"}
    assert "methodology" in payload and payload["methodology"].strip()
    assert "field_dictionary" in payload

    if payload["status"] == "ok":
        # Live SEC text came back — assert it's real, not the old template.
        assert payload["utterances"], "ok status must carry utterances"
        assert payload["data_mode"] in {"live_official", "cached_snapshot"}
        assert "sec_edgar" in result.sources or "transcripts_archive" in result.sources
        blob = " ".join(r["utterance"] for r in payload["utterances"]).lower()
        assert "placeholders are structured for downstream search" not in blob
        for r in payload["utterances"]:
            assert {"section", "speaker", "role", "utterance"} <= set(r)
    else:
        # Network down / no exhibit — must be honest, never fabricated.
        assert payload["utterances"] == []
        assert payload["rows"] == []
        assert payload.get("next_actions")
        assert payload["data_mode"] in {"provider_unavailable", "not_configured"}


def test_no_instrument_raises() -> None:
    fn = TRANFunction()
    with pytest.raises(ValueError):
        _run(fn.execute(None))
