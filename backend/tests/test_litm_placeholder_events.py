"""LITM must not count a placeholder entry in events_8k as a scanned filing.

Review of LITM#1 (P0 wave, 2026-11-08): a placeholder ({category, status: provider_unavailable}) in
events_8k was counted as one scanned 8-K and reported "no_litigation_event_found" after a "full scan"
of zero filings. CACT is faked here so the placeholder reaches LITM directly.
"""
from __future__ import annotations

import asyncio

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.misc import _bonus

PLACEHOLDER = {"category": "corporate_actions", "status": "provider_unavailable"}


def _run(monkeypatch, cact_data):
    from showme.engine.functions.equity import cact

    async def fake_cact(self, instrument=None, **params):
        return FunctionResult(code="CACT", instrument=instrument, data=cact_data,
                              sources=["awareness:filings"])

    monkeypatch.setattr(cact.CACTFunction, "execute", fake_cact)
    fn = _bonus.LITMFunction(FunctionDeps())
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=inst)).data


def test_placeholder_is_not_a_scanned_8k(monkeypatch):
    data = _run(monkeypatch, {"status": "empty", "events_8k": [PLACEHOLDER]})
    row = data["rows"][0]
    assert data["scanned_8k"] == 0
    assert row.get("scanned_8k", 0) == 0
    assert row["event_type"] != "no_litigation_event_found"
    assert row["event_type"] == "no_8k_filings_in_window"
    assert data["status"] == "empty"


def test_cact_unavailable_is_unavailable_not_a_scan(monkeypatch):
    data = _run(monkeypatch, {"status": "provider_unavailable", "reason": "awareness down", "events_8k": []})
    assert data["status"] == "provider_unavailable"
    assert data["reason"] == "awareness down"
    assert data["rows"][0].get("all_8k_events", 0) == 0


def test_real_8k_without_matching_item_is_still_a_verified_absence(monkeypatch):
    filing = {"accession": "0000320193-26-000011", "filing_date": "2026-08-02", "document": "https://sec.example/k.htm",
              "form": "8-K", "items": "2.02,9.01", "item_codes": ["2.02", "9.01"], "code": "2.02",
              "category": "Results of Operations", "source": "awareness:filings"}
    data = _run(monkeypatch, {"status": "ok", "events_8k": [PLACEHOLDER, filing]})
    row = data["rows"][0]
    assert row["event_type"] == "no_litigation_event_found"
    assert row["scanned_8k"] == 1
