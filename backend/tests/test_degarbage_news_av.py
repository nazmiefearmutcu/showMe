"""Degarbage tests for the AV (Audio / Video Archive) news function.

The old AV ``execute()`` returned a hardcoded ``_media_template()`` placeholder
list with ``status="model"`` on the default path. These tests assert the
fixed function:

* never returns the old canned placeholder rows on the default path;
* with a symbol, builds a real archive from keyless SEC EDGAR filings whose
  ``play_url`` is a live HTTPS SEC link (and degrades to a clearly-labelled
  ``provider_unavailable`` shape offline);
* always exposes ``methodology`` + ``field_dictionary`` + ``cards``.

Live-network assertions are guarded: if the fetch raises a network error the
handler is required to return the graceful ``provider_unavailable`` shape, and
the test accepts that instead of failing offline.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news.av import AVFunction


_OK_SET = {"ok", "empty", "provider_unavailable"}
_OLD_PLACEHOLDER_TITLES = {
    "Macro and market briefing",
    "Sample earnings call replay",
}


def _run(coro):
    return asyncio.run(coro)


def _assert_common_contract(payload: dict) -> None:
    assert payload["status"] in _OK_SET, payload.get("status")
    assert isinstance(payload.get("rows"), list)
    assert payload.get("methodology"), "methodology must be present"
    assert isinstance(payload.get("field_dictionary"), dict) and payload["field_dictionary"]
    assert isinstance(payload.get("cards"), dict)
    # The old canned placeholder rows must never appear.
    for row in payload["rows"]:
        assert row.get("title") not in _OLD_PLACEHOLDER_TITLES, row


def test_av_symbol_archive_is_real_or_graceful():
    """With a symbol, AV builds a live SEC-backed archive or degrades cleanly."""
    fn = AVFunction()
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=inst))
    payload = result.data
    _assert_common_contract(payload)

    if payload["status"] == "ok":
        assert payload["rows"], "ok status must carry real rows"
        # Honest provider name.
        assert "sec_edgar" in result.sources
        for row in payload["rows"]:
            url = str(row.get("play_url") or row.get("url") or "")
            assert url.startswith("http"), f"play_url must be a real http(s) link: {url!r}"
            assert "sec.gov" in url, url
            assert row.get("symbol") == "AAPL"
            assert row.get("event_date"), "filings must be time-anchored"
            assert row.get("media_type")
    else:
        # Offline / rate-limited: must be the labelled graceful fallback.
        assert payload["status"] in {"provider_unavailable", "empty"}
        assert payload.get("reason")
        assert payload.get("next_actions")


def test_av_global_archive_no_symbol_is_real_or_graceful():
    """No symbol -> global podcast archive of real playable audio, or graceful."""
    fn = AVFunction()
    result = _run(fn.execute(instrument=None))
    payload = result.data
    _assert_common_contract(payload)

    if payload["status"] == "ok":
        assert payload["rows"]
        assert "podcast_rss" in result.sources
        # Real, time-anchored, playable rows — not the old template.
        has_playable = any(
            str(r.get("play_url") or r.get("url") or "").startswith("http")
            for r in payload["rows"]
        )
        assert has_playable, "global archive rows must carry real playable URLs"
    else:
        assert payload["status"] == "provider_unavailable"
        assert payload.get("reason")
        assert payload.get("next_actions")


def test_av_default_path_is_not_canned_status_model():
    """The default path must never return the removed status='model' stub."""
    fn = AVFunction()
    inst = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=inst))
    assert result.data["status"] != "model"
    assert "podcast_directory_model" not in result.sources


def test_av_unmapped_symbol_degrades_to_global_or_graceful():
    """A symbol with no SEC filer falls back to global media (or graceful)."""
    fn = AVFunction()
    inst = Instrument(symbol="ZZZZNOTAREALTICKER", asset_class=AssetClass.EQUITY)
    result = _run(fn.execute(instrument=inst))
    payload = result.data
    assert payload["status"] in _OK_SET
    assert isinstance(payload.get("rows"), list)
    assert payload.get("methodology")


@pytest.mark.parametrize("dur,expected", [
    (None, None),
    ("", None),
    ("3600", 3600),
    ("01:02:03", 3723),
    ("12:30", 750),
    ("garbage", None),
])
def test_av_parse_duration(dur, expected):
    from showme.engine.functions.news.av import _parse_duration

    assert _parse_duration(dur) == expected


def test_av_query_filter_rejects_generic_noise():
    """Query matching must not match a row on stop words alone."""
    from showme.engine.functions.news.av import _matches_query

    row = {"title": "Apple 8-K Material Event", "symbol": "AAPL", "form": "8-K"}
    assert _matches_query(row, "") is True
    assert _matches_query(row, "apple") is True
    assert _matches_query(row, "tesla") is False
    # pure stop word -> no spurious match
    assert _matches_query(row, "podcast") is False
