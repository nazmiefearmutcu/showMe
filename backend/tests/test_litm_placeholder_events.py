"""LITM must not count CACT's placeholder 8-K entry as a scanned filing.

Review of LITM#1 (P0 wave, 2026-11-08): when the EDGAR feed has an items
column but no 8-K rows, CACT puts {category: corporate_actions, status:
provider_unavailable} into events_8k; LITM counted it as one scanned 8-K and
reported "no_litigation_event_found" after a "full scan" of zero filings.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.misc import _bonus

PLACEHOLDER = {"category": "corporate_actions", "status": "provider_unavailable"}


def _run(monkeypatch, events, frame):
    from showme.engine.functions.equity import cact

    async def fake_cact(self, instrument=None, **params):
        return FunctionResult(code="CACT", instrument=instrument,
                              data={"events_8k": events, "sec_filings": frame})

    monkeypatch.setattr(cact.CACTFunction, "execute", fake_cact)
    fn = _bonus.LITMFunction(FunctionDeps(sec_edgar=object()))
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument=inst)).data


def test_placeholder_is_not_a_scanned_8k(monkeypatch):
    frame = pd.DataFrame([{"form": "10-Q", "items": "", "accessionNumber": "0000320193-26-000010",
                           "filingDate": "2026-08-01", "reportDate": "2026-06-30", "primaryDocument": "q.htm"}])
    data = _run(monkeypatch, [PLACEHOLDER], frame)
    row = data["rows"][0]
    assert row.get("scanned_8k", 0) == 0
    assert row["event_type"] != "no_litigation_event_found"
    assert row["event_type"] == "no_8k_filings_in_window"
    assert data["status"] == "empty"


def test_placeholder_without_a_feed_is_unavailable(monkeypatch):
    data = _run(monkeypatch, [PLACEHOLDER], None)
    assert data["status"] == "provider_unavailable"
    assert data["rows"][0].get("all_8k_events", 0) == 0


def test_real_8k_without_matching_item_is_still_a_verified_absence(monkeypatch):
    frame = pd.DataFrame([{"form": "8-K", "items": "2.02,9.01", "accessionNumber": "0000320193-26-000011",
                           "filingDate": "2026-08-02", "reportDate": "2026-08-01", "primaryDocument": "k.htm"}])
    data = _run(monkeypatch, [PLACEHOLDER], frame)
    row = data["rows"][0]
    assert row["event_type"] == "no_litigation_event_found"
    assert row["scanned_8k"] == 1
