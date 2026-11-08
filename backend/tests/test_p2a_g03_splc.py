"""P2A-G03 regression tests: SPLC#3 (relationship / min_pct / source_url).

Offline: SEC EDGAR fetch and the httpx client are faked.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import splc as splc_mod


def _run(coro):
    return asyncio.run(coro)


# ---------------------------------------------------------------------------
# SPLC#3 — relationship / min_pct are applied and rows carry source_url
# ---------------------------------------------------------------------------

_FILING_URL = (
    "https://www.sec.gov/Archives/edgar/data/320193/"
    "000032019326000001/aapl-20260926.htm"
)
_FILING_HTML = (
    "<html><body><p>Major customers: Beta Corp represented 22% of net sales. "
    "Gamma Ltd accounted for 6% of net sales.</p>"
    "<p>Major suppliers: Foundry Inc accounted for 15% of inputs.</p>"
    "</body></html>"
)


class _FakeSec:
    async def fetch(self, req: Any) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "form": "10-K",
                    "accessionNumber": "0000320193-26-000001",
                    "primaryDocument": "aapl-20260926.htm",
                    "filingDate": "2026-10-30",
                }
            ]
        )

    async def cik_for(self, symbol: str) -> int:
        return 320193


class _FakeResponse:
    status_code = 200
    text = _FILING_HTML


class _FakeClient:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    async def __aenter__(self) -> "_FakeClient":
        return self

    async def __aexit__(self, *exc: Any) -> bool:
        return False

    async def get(self, url: str) -> _FakeResponse:
        assert url == _FILING_URL
        return _FakeResponse()


@pytest.fixture
def splc_filing(monkeypatch: pytest.MonkeyPatch):
    import httpx

    monkeypatch.setattr(httpx, "AsyncClient", _FakeClient)


def _splc(**params: Any) -> Any:
    fn = splc_mod.SPLCFunction(FunctionDeps(sec_edgar=_FakeSec()))
    instrument = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return _run(fn.execute(instrument, **params))


def test_splc_relationship_filter_is_applied(splc_filing) -> None:
    both = _splc()
    customers_only = _splc(relationship="customer")
    suppliers_only = _splc(relationship="supplier")

    assert any(r["relationship"] == "customer" for r in both.data["rows"])
    assert any(r["relationship"] == "supplier" for r in both.data["rows"])
    assert customers_only.data["rows"]
    assert all(r["relationship"] == "customer" for r in customers_only.data["rows"])
    assert suppliers_only.data["rows"]
    assert all(r["relationship"] == "supplier" for r in suppliers_only.data["rows"])


def test_splc_min_pct_drops_rows_below_disclosed_share(splc_filing) -> None:
    result = _splc(min_pct=10)
    rows = result.data["rows"]

    assert rows
    assert all(r["disclosed_pct"] is not None and r["disclosed_pct"] >= 10 for r in rows)
    assert any(r["counterparty"] == "Beta Corp" for r in rows)
    assert not any(r["counterparty"] == "Gamma Ltd" for r in rows)


def test_splc_extracted_rows_carry_source_url(splc_filing) -> None:
    result = _splc(relationship="customer")
    extracted = [r for r in result.data["rows"] if r["source_mode"].startswith("sec_10k")]

    assert extracted
    assert all(r["source_url"] == _FILING_URL for r in extracted)
    assert "source_url" in result.data["field_dictionary"]
