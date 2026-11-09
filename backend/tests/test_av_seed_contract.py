"""AV manifest describes the sources and inputs it really has (AV#6).

The seed methodology used to describe a media-archive backend
(engine/services/media_archive, transcripts_archive, asset manifests) that does
not exist. Inputs media_type, has_transcript and provider_mode were declared
but never read. The contract now names SEC EDGAR and podcast RSS, implements
media_type as a real filter, and drops the two inputs that could never match.
Network is patched.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.news import av as av_mod
from showme.engine.functions.news.av import AVFunction
from showme.manifest import REGISTRY, load_seeds

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _entry():
    load_seeds()
    return REGISTRY.get("AV")


def test_methodology_names_real_sources_only():
    text = _entry().methodology.lower()
    assert "sec edgar" in text
    assert "podcast" in text
    assert "media_archive" not in text
    assert "transcripts_archive" not in text
    assert "playable archive" in text


def test_declared_inputs_are_all_read_by_the_handler():
    names = {spec.name for spec in _entry().inputs}
    assert "has_transcript" not in names
    assert "provider_mode" not in names
    assert {"symbol", "media_type", "date_range"} <= names


def test_media_type_options_match_what_rows_carry():
    spec = next(s for s in _entry().inputs if s.name == "media_type")
    assert set(spec.options) == {"filing", "podcast"}


def _sec(monkeypatch):
    fn = AVFunction()
    today = datetime.now(timezone.utc).date()
    d = (today - timedelta(days=4)).isoformat()

    async def _cik(symbol, params):
        return 320193

    async def _get_json(url, headers, timeout):
        return {
            "filings": {
                "recent": {
                    "form": ["10-K"],
                    "filingDate": [d],
                    "reportDate": [d],
                    "accessionNumber": ["0000320193-26-000026"],
                    "primaryDocument": ["aapl-10k.htm"],
                    "primaryDocDescription": ["10-K"],
                    "items": [""],
                }
            }
        }

    monkeypatch.setattr(fn, "_resolve_cik", _cik)
    monkeypatch.setattr(av_mod, "_get_json", _get_json)
    return fn


def test_media_type_filter_selects_rows(monkeypatch):
    fn = _sec(monkeypatch)
    kept = asyncio.run(fn.execute(instrument=AAPL, media_type=["filing"])).data
    assert kept["status"] == "ok"
    assert len(kept["rows"]) == 1

    dropped = asyncio.run(fn.execute(instrument=AAPL, media_type=["podcast"])).data
    assert dropped["status"] == "empty"
    assert dropped["rows"] == []
