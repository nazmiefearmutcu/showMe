"""SPLC#1 follow-up: an undated share never displaces a dated one, in either order.

A disclosure whose sentence names a fiscal year is preferred over one that
names none, because only its period is verifiable; between two dated shares the
later fiscal year wins. A row whose only disclosure is undated still reports no
year rather than a guess.

Offline: the EDGAR fetch and the httpx client are faked; no network is used.
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


def test_undated_share_listed_first_is_displaced_by_a_dated_prior_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The dated FY2025 share is labelled, so it is shown with its year; the undated
    # 22% cannot be dated and does not win over a dated disclosure.
    html = (
        "<p>Major customers: Sales to one direct customer represented 22% of total revenue. "
        "For fiscal year 2025, sales to one direct customer represented 12% of total revenue.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _run(relationship="customer")

    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [("One direct customer", 12.0)]
    assert result.data["customers"][0]["fiscal_year"] == 2025
    assert result.data["rows"][0]["fiscal_year"] == 2025


def test_dated_share_listed_first_is_kept_over_a_later_undated_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<p>Major customers: For fiscal year 2025, sales to one direct customer represented 12% of "
        "total revenue. Sales to one direct customer represented 22% of total revenue.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _run(relationship="customer")

    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [("One direct customer", 12.0)]
    assert result.data["customers"][0]["fiscal_year"] == 2025


def test_dated_share_listed_after_an_undated_one_is_reported_with_its_year(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<p>Major customers: Sales to one direct customer represented 12% of total revenue. "
        "For fiscal year 2026, sales to one direct customer represented 22% of total revenue.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _run(relationship="customer")

    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [("One direct customer", 22.0)]
    assert result.data["customers"][0]["fiscal_year"] == 2026
    assert result.data["rows"][0]["fiscal_year"] == 2026
