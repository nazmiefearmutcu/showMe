"""LITM must see 8-K item codes from the real SEC EDGAR filing rows.

Regression for LITM#1: the default live path ran CACT with max_documents=1 and
CACT's 8-K rows carry no item code, so every ticker (AAPL included) came back as
a false "no litigation event". The real CACT runs here; only the SEC EDGAR
adapter is faked, with a frame shaped like the submissions "recent" block.
"""

from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.misc._bonus import LITMFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _frame(with_items: bool = True) -> pd.DataFrame:
    data = {
        "form": ["10-Q", "8-K", "8-K/A", "2.5", "8-K"],
        "filingDate": ["2026-08-01", "2026-11-02", "2026-09-01", "2026-07-01", "2026-04-20"],
        "reportDate": ["2026-06-27", "2026-11-02", "2026-09-01", "2026-07-01", "2026-04-20"],
        "accessionNumber": ["A-1", "A-2", "A-3", "A-4", "A-5"],
        "primaryDocument": ["q.htm", "k1.htm", "k2.htm", "x.htm", "k3.htm"],
    }
    if with_items:
        data["items"] = ["", "2.02,9.01", "5.02", "", "5.02"]
    return pd.DataFrame(data)


class _Edgar:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, request):
        return self._frame

    async def cik_for(self, symbol):
        return "0000320193"


def _run(frame: pd.DataFrame):
    deps = FunctionDeps(sec_edgar=_Edgar(frame))
    return asyncio.run(LITMFunction(deps).execute(instrument=AAPL))


def test_litm_reports_item_502_from_non_newest_8k() -> None:
    result = _run(_frame())
    assert result.data["status"] == "ok", result.data
    codes = [r["item_code"] for r in result.data["rows"]]
    assert "5.02" in codes
    accessions = {r["accession"] for r in result.data["rows"]}
    assert "A-3" in accessions and "A-5" in accessions
    assert "2.02" not in " ".join(codes)


def test_litm_scans_every_8k_row_not_just_one() -> None:
    result = _run(_frame())
    assert result.data["all_8k_events"] == 3
    assert result.data["scanned_8k"] == 3


def test_litm_without_item_codes_is_not_reported_as_empty() -> None:
    result = _run(_frame(with_items=False))
    # Filing rows give no way to classify items: that is a provider gap, not
    # a verified absence of litigation events.
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"][0]["event_type"] != "no_litigation_event_found"
