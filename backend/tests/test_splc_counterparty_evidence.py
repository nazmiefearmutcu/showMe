"""SPLC#1 follow-up: a counterparty label needs counterparty evidence, and a dated share wins.

* A business segment, product line or unit named without a segment keyword
  ("Data Center accounted for 80% of total revenue" after a "Major customers"
  heading) must not become a customer. A label is kept only when its sentence
  uses customer/supplier wording or the name carries a corporate designator.
  Residual: a major customer named with neither (e.g. "Walmart accounted for
  13%") is not extracted; it is dropped rather than mislabelled.
* A share whose sentence names a fiscal year is preferred over an undated one,
  whichever comes first in the filing; between dated shares the later year wins.

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


def test_business_unit_named_without_a_segment_keyword_is_not_a_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_filing_html(
        monkeypatch,
        "<p>Major customers: Data Center accounted for 80% of total revenue.</p>",
    )

    result = _run(relationship="customer")

    assert result.data["customers"] == []
    assert all(r["counterparty"] != "Data Center" for r in result.data["rows"])


def test_designated_company_after_customer_heading_is_still_a_customer(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_filing_html(
        monkeypatch,
        "<p>Major customers: Beta Corp accounted for 22% of net sales.</p>",
    )

    result = _run(relationship="customer")

    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [("Beta Corp", 22.0)]


def test_supplier_named_with_supplier_wording_is_kept(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_filing_html(
        monkeypatch,
        "<p>Major suppliers: Contract supplier Zeta accounted for 15% of inputs.</p>",
    )

    result = _run(relationship="supplier")

    assert [r["name"] for r in result.data["suppliers"]] == ["Contract supplier Zeta"]


def test_clean_counterparty_rejects_bare_business_unit_names() -> None:
    clean = splc_mod._clean_counterparty
    assert clean("Data Center") is None
    assert clean("Gaming") is None
    assert clean("Beta Corp") == "Beta Corp"
    assert clean("Foundry Inc") == "Foundry Inc"
    assert clean("Sales to one direct customer") == "One direct customer"


def test_trailing_comma_before_the_verb_is_not_part_of_the_label(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_filing_html(
        monkeypatch,
        "<p>Major customers: Beta Corp, accounted for 22% of net sales.</p>",
    )

    result = _run(relationship="customer")

    assert [r["name"] for r in result.data["customers"]] == ["Beta Corp"]
