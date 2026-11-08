"""PIB#1 / PIB#2 regressions: server-side months and form filters, honest
summary status, and an absolute EDGAR document URL.

Network is never touched; SEC EDGAR is replaced by an in-memory fake.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.pib import PIBFunction


def _run(coro):
    return asyncio.run(coro)


class _FakeEdgar:
    def __init__(self, frame: pd.DataFrame, cik: str = "0000320193") -> None:
        self.frame = frame
        self.cik = cik

    async def fetch(self, request):  # noqa: ARG002
        return self.frame.copy()

    async def cik_for(self, ticker):  # noqa: ARG002
        return self.cik


def _filings(today: datetime) -> pd.DataFrame:
    def d(days_ago: int) -> str:
        return (today - timedelta(days=days_ago)).date().isoformat()

    return pd.DataFrame({
        "accessionNumber": [
            "0000320193-26-000030", "0000320193-26-000025",
            "0000320193-26-000020", "0000320193-26-000010",
        ],
        "filingDate": [d(5), d(40), d(120), d(200)],
        "reportDate": [d(6), d(41), d(121), d(201)],
        "form": ["8-K", "10-Q", "10-K", "10-K"],
        "primaryDocument": ["a8k.htm", "aq.htm", "ak.htm", "ak2025.htm"],
    })


def _pib_res(deps, **params):
    from showme.engine.core.instrument import Instrument as _I
    return _run(PIBFunction(deps).execute(
        instrument=_I(symbol="AAPL", asset_class=AssetClass.EQUITY), **params,
    ))


def test_pib_applies_months_and_form_filters():
    today = datetime.now(timezone.utc)
    deps = FunctionDeps(sec_edgar=_FakeEdgar(_filings(today)))
    res = _pib_res(deps, months=6, form_types=["10-K"])
    rows = res.data["rows"]
    # 10-K filed 120 days ago is inside 6 months; the 200-day-old 10-K is not.
    assert [r["accession"] for r in rows] == ["0000320193-26-000020"]
    assert all(r["form"] == "10-K" for r in rows)


def test_pib_months_window_excludes_older_filings():
    today = datetime.now(timezone.utc)
    deps = FunctionDeps(sec_edgar=_FakeEdgar(_filings(today)))
    res = _pib_res(deps, months=3)
    assert sorted(r["form"] for r in res.data["rows"]) == ["10-Q", "8-K"]


def test_pib_include_summary_is_honestly_not_implemented():
    today = datetime.now(timezone.utc)
    deps = FunctionDeps(sec_edgar=_FakeEdgar(_filings(today)))
    res = _pib_res(deps, include_summary=True)
    assert res.data.get("summary") is None
    assert res.data.get("summary_status") == "not_implemented"
    assert any("summary" in w.lower() for w in res.warnings)


def test_pib_filing_url_is_absolute_edgar_document_link():
    today = datetime.now(timezone.utc)
    deps = FunctionDeps(sec_edgar=_FakeEdgar(_filings(today)))
    res = _pib_res(deps, months=12)
    row = next(r for r in res.data["rows"] if r["accession"] == "0000320193-26-000030")
    assert row["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000032019326000030/a8k.htm"
    )


def test_pib_unavailable_feed_reports_no_fake_rows_or_sources():
    res = _pib_res(FunctionDeps(sec_edgar=None))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["rows"] == []
    assert res.sources == []
    assert "pib_model" not in res.sources


def test_pib_seed_table_columns_match_emitted_row_keys():
    from showme.manifest.seeds.pib_seed import pib

    emitted = {"symbol", "section", "form", "filingDate", "reportDate", "accession", "url", "source_mode"}
    for col in pib.table_schema.columns:
        assert col.key in emitted, col.key
