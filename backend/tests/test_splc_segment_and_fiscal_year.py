"""SPLC#1 follow-up: segment shares and prior-year shares are not counterparties.

Offline: the EDGAR fetch and the httpx client are faked; no network is used.

* A business segment's share of revenue ("Compute and Networking segment
  accounted for 80% of total revenue") after a "Major customers" heading was
  reported as a customer with a disclosed share.
* The first disclosure per label in document order won, so a prior fiscal
  year (FY2025 listed before FY2026) was reported as the current share with no
  as-of year. Each row now carries the fiscal year its sentence names, and the
  latest disclosed year per counterparty wins.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import splc as splc_mod

_FILING_URL = "https://www.sec.gov/Archives/edgar/data/1045810/000104581026000021/nvda-20260125.htm"


class _FakeSec:
    async def fetch(self, req: Any) -> pd.DataFrame:
        return pd.DataFrame([{
            "form": "10-K",
            "accessionNumber": "0001045810-26-000021",
            "primaryDocument": "nvda-20260125.htm",
            "filingDate": "2026-02-25",
        }])

    async def cik_for(self, symbol: str) -> int:
        return 1045810


def _patch_filing_html(monkeypatch: pytest.MonkeyPatch, html: str) -> None:
    import httpx

    class _Resp:
        status_code = 200
        text = html

    class _Client:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "_Client":
            return self

        async def __aexit__(self, *exc: Any) -> bool:
            return False

        async def get(self, url: str) -> _Resp:
            assert url == _FILING_URL
            return _Resp()

    monkeypatch.setattr(httpx, "AsyncClient", _Client)


def _run(**params: Any) -> Any:
    fn = splc_mod.SPLCFunction(FunctionDeps(sec_edgar=_FakeSec()))
    instrument = Instrument(symbol="NVDA", asset_class=AssetClass.EQUITY)
    return asyncio.run(fn.execute(instrument, **params))


def test_segment_share_after_major_customers_heading_is_not_a_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<p>Major customers are discussed below. Compute and Networking segment accounted for "
        "80% of total revenue. Sales to one direct customer represented 22% of total revenue.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _run(relationship="customer")

    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [("One direct customer", 22.0)]


def test_prior_fiscal_year_is_not_reported_as_the_current_share(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<p>Major customers: For fiscal year 2025, sales to one direct customer represented 12% of "
        "total revenue. For fiscal year 2026, sales to one direct customer represented 22% of total "
        "revenue.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _run(relationship="customer")

    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [("One direct customer", 22.0)]
    assert result.data["customers"][0]["fiscal_year"] == 2026
    assert result.data["rows"][0]["fiscal_year"] == 2026


def test_disclosure_that_names_no_fiscal_year_reports_none_not_a_guess(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_filing_html(monkeypatch, "<p>Major customers: Beta Corp represented 22% of net sales.</p>")

    result = _run(relationship="customer")

    assert result.data["rows"][0]["counterparty"] == "Beta Corp"
    assert result.data["rows"][0]["fiscal_year"] is None
