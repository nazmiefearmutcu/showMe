"""SPLC#2 (wc3-g05): static AAPL reference relationships must not look extracted.

The hand-written customer/supplier entries carry no 10-K extraction and no
measured confidence, so they must not be labelled as 10-K language or given
confidence numbers. Offline: SEC EDGAR and the httpx client are faked.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import splc as splc_mod

_FILING_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019326000001/aapl-20260926.htm"
)


class _FakeSec:
    async def fetch(self, req: Any) -> pd.DataFrame:
        return pd.DataFrame([{
            "form": "10-K",
            "accessionNumber": "0000320193-26-000001",
            "primaryDocument": "aapl-20260926.htm",
            "filingDate": "2026-10-30",
        }])

    async def cik_for(self, symbol: str) -> int:
        return 320193


class _NoConcentrationResponse:
    status_code = 200
    text = "<html><body><p>Our business is described here with no concentration figures.</p></body></html>"


class _FakeClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get(self, url: str) -> _NoConcentrationResponse:
        assert url == _FILING_URL
        return _NoConcentrationResponse()


@pytest.fixture
def no_extraction(monkeypatch: pytest.MonkeyPatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)


def _reference_rows() -> list[dict[str, Any]]:
    fn = splc_mod.SPLCFunction(FunctionDeps(sec_edgar=_FakeSec()))
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    res = asyncio.run(fn.execute(instrument))
    assert res.data["status"] == "reference_relationships", res.data["status"]
    return [r for r in res.data["rows"] if r.get("source_mode", "").startswith("reference_supply_chain")]


def test_static_reference_rows_are_not_labelled_as_10k_extraction(no_extraction) -> None:
    rows = _reference_rows()
    assert rows, "expected static AAPL reference relationship rows"
    # RED before fix: source_mode was "reference_supply_chain_10k_language" and
    # the source text said "10-K ... language".
    for row in rows:
        assert "10k" not in str(row.get("source_mode", "")).lower(), row
        assert "10-k" not in str(row.get("source", "")).lower(), row


def test_static_reference_rows_carry_no_invented_confidence(no_extraction) -> None:
    # RED before fix: fixed confidences 0.62-0.72 were shown as if measured.
    rows = _reference_rows()
    assert rows
    for row in rows:
        assert row.get("confidence") is None, row


def test_competitor_rows_on_reference_branch_carry_no_invented_confidence(no_extraction) -> None:
    # SPLC#2 follow-up: the reference branch also emits competitor rows
    # (source_mode reference_sector_peer_list), which the prefix filter above skips.
    fn = splc_mod.SPLCFunction(FunctionDeps(sec_edgar=_FakeSec()))
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    res = asyncio.run(fn.execute(instrument))
    competitors = [r for r in res.data["rows"] if r.get("relationship") == "competitor"]
    assert competitors, "expected competitor peer rows on the AAPL reference branch"
    for row in competitors:
        assert row.get("confidence") is None, row


def test_sec_path_competitor_rows_carry_no_invented_confidence() -> None:
    # SPLC#2 follow-up: the SEC-extracted path also emits peer competitor rows
    # through _relationship_rows; those must not carry the fixed 0.35 score.
    rows = splc_mod._relationship_rows(
        "AAPL",
        [{"name": "Carrier X", "pct": 12.0, "confidence": 0.6}],
        [],
        pd.DataFrame(),
        peers=["MSFT", "GOOGL"],
        filing_url=_FILING_URL,
    )
    competitors = [r for r in rows if r.get("relationship") == "competitor"]
    assert len(competitors) == 2, rows
    for row in competitors:
        assert row.get("confidence") is None, row
    # Extracted customer rows keep their own extraction confidence.
    customer = next(r for r in rows if r.get("relationship") == "customer")
    assert customer.get("confidence") == 0.6
