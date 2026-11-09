"""P2A-G03 review regressions for SPLC#1: concentration extraction on real 10-K shapes.

Offline: the SEC EDGAR fetch and the httpx client are faked; no network is used.
The NVDA excerpt below is a trimmed, tag-stripped passage from the FY2026 10-K
(accession 0001045810-26-000021) "Concentration of Revenue" MD&A section.
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


_FILING_URL = (
    "https://www.sec.gov/Archives/edgar/data/1045810/"
    "000104581026000021/nvda-20260125.htm"
)

# Live-shaped passage: the percentage sentence sits about 700 characters after the
# "Concentration of Revenue" heading, and the 10-K text carries &#8211; entities.
_NVDA_SECTION = (
    "<p>Concentration of Revenue We refer to customers who purchase products directly "
    "from NVIDIA as direct customers, such as AIBs, distributors, ODMs, OEMs, CSPs, AI "
    "model makers, and system integrators. Certain direct customers may use either "
    "internal resources or third-party system integrators to complete their build. We "
    "refer to indirect customers as those who purchase products through our direct "
    "customers. Our revenue is concentrated among a limited number of direct and indirect "
    "customers and this trend may continue. Direct Customers &#8211; For fiscal year 2026, "
    "sales to one direct customer represented 22% of total revenue and sales to another "
    "direct customer represented 14% of total revenue, all of which were primarily "
    "attributable to the Compute &amp; Networking segment. For fiscal year 2025, sales to "
    "one direct customer represented 12% of total revenue and sales to two direct "
    "customers each represented 11% of total revenue, all of which were primarily "
    "attributable to the Compute &amp; Networking segment.</p>"
)


class _FakeSec:
    async def fetch(self, req: Any) -> pd.DataFrame:
        return pd.DataFrame(
            [
                {
                    "form": "10-K",
                    "accessionNumber": "0001045810-26-000021",
                    "primaryDocument": "nvda-20260125.htm",
                    "filingDate": "2026-02-25",
                }
            ]
        )

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


def _nvda(**params: Any) -> Any:
    fn = splc_mod.SPLCFunction(FunctionDeps(sec_edgar=_FakeSec()))
    instrument = Instrument(symbol="NVDA", asset_class=AssetClass.EQUITY)
    return _run(fn.execute(instrument, **params))


def test_nvda_live_shape_returns_the_2026_direct_customer_pair(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_filing_html(monkeypatch, f"<html><body>{_NVDA_SECTION}</body></html>")

    result = _nvda(relationship="customer")

    # Document order keeps the FY2026 disclosure; the FY2025/FY2024 repeats of the
    # same labels are not reported as if they were current shares.
    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [
        ("One direct customer", 22.0),
        ("Another direct customer", 14.0),
    ]
    assert [r["counterparty"] for r in result.data["rows"]] == [
        "One direct customer",
        "Another direct customer",
    ]
    assert all(r["source_url"] == _FILING_URL for r in result.data["rows"])
    assert result.data["status"] == "ok"


def test_percentage_sentence_far_after_heading_is_still_scanned(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # About 5,000 characters separate the heading from the sentence; the former
    # 3,000-character cap dropped this case.
    html = (
        "<p>Major customers are discussed below. "
        + ("Filler text. " * 420)
        + "Sales to one direct customer represented 22% of total revenue and sales to "
        "another direct customer represented 14% of total revenue.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _nvda(relationship="customer")

    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [
        ("One direct customer", 22.0),
        ("Another direct customer", 14.0),
    ]


def test_supplier_heading_closes_the_customer_window(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<p>Major customers: Beta Corp represented 22% of net sales. "
        "Major suppliers: Foundry Inc accounted for 15% of inputs. "
        "Quarterly notes; Zeta Ltd represented 9% of net sales.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _nvda(relationship="customer")

    assert [r["name"] for r in result.data["customers"]] == ["Beta Corp"]


def test_counterparty_label_is_kept_once_per_name_in_document_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<p>Major customers: Beta Corp represented 22% of net sales in fiscal 2026.</p>"
        "<p>Major customers: Beta Corp accounted for 12% of net sales in fiscal 2025.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _nvda(relationship="customer")

    assert [(r["name"], r["pct"]) for r in result.data["customers"]] == [("Beta Corp", 22.0)]


def test_sales_to_prefix_is_stripped_from_counterparty_label() -> None:
    clean = splc_mod._clean_counterparty
    assert clean("Sales to Foo Corp") == "Foo Corp"
    assert clean("net sales to Foo Corp") == "Foo Corp"
    assert clean("Sales to one direct customer") == "One direct customer"
    assert clean("revenue from Gamma Ltd") == "Gamma Ltd"


def test_overlong_or_lowercase_fragments_are_not_labels() -> None:
    clean = splc_mod._clean_counterparty
    assert clean(
        "Some Company Holdings Limited and its consolidated subsidiaries across every segment"
    ) is None
    assert clean("and sales to Beta Corp") is None


def test_html_entities_are_decoded_before_extraction(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = (
        "<p>Major customers &#8211; Sales to one direct customer represented 22&#160;% "
        "of total revenue.</p>"
    )
    _patch_filing_html(monkeypatch, html)

    result = _nvda(relationship="customer")

    assert [(r["counterparty"], r["disclosed_pct"]) for r in result.data["rows"]] == [
        ("One direct customer", 22.0),
    ]


def test_filters_that_remove_every_row_report_an_empty_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    html = "<p>Major customers: Beta Corp represented 22% of net sales.</p>"
    _patch_filing_html(monkeypatch, html)

    result = _nvda(min_pct=50)

    assert result.data["rows"] == []
    assert result.data["customers"] == []
    assert result.data["suppliers"] == []
    assert result.data["status"] == "empty"
    assert result.data["reason"]
    assert result.data["filters_applied"] == {"relationship": "both", "min_pct": 50.0}
