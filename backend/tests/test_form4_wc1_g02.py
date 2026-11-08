"""FORM4 review findings FORM4#2..#8 (wc1-g02).

Each block pins one finding. Network is patched: yfinance and SEC are fakes.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import form4 as form4_mod
from showme.engine.functions.equity.form4 import FORM4Function


class _YF:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, _request: Any) -> dict[str, Any]:
        return {"insider_transactions": self._frame}


# ─── FORM4#3: SEC transaction codes must map to the right direction ──────


def test_form4_3_sec_exercise_codes_x_and_m_are_neutral_not_sales() -> None:
    # X / M = exercise of a derivative: acquires common stock, no market sale.
    assert form4_mod._infer_direction({"acquiredDisposedCode": "X"}) == 0
    assert form4_mod._infer_direction({"acquiredDisposedCode": "M"}) == 0


def test_form4_3_sec_grant_and_expiration_codes_are_neutral_not_buys() -> None:
    # A = grant/award (no open-market purchase); E = expiration of a short position.
    assert form4_mod._infer_direction({"acquiredDisposedCode": "A"}) == 0
    assert form4_mod._infer_direction({"acquiredDisposedCode": "E"}) == 0


def test_form4_3_sec_open_market_codes_keep_their_sign() -> None:
    assert form4_mod._infer_direction({"acquiredDisposedCode": "P"}) == 1
    assert form4_mod._infer_direction({"acquiredDisposedCode": "S"}) == -1


def test_form4_3_normalized_types_do_not_call_exercise_a_sell() -> None:
    assert form4_mod._normalize_transaction_type("x") == "option_exercise"
    assert form4_mod._normalize_transaction_type("m") == "option_exercise"
    assert form4_mod._normalize_transaction_type("a") == "grant"
    assert form4_mod._normalize_transaction_type("s") == "sell"


def test_form4_3_exercise_row_moves_no_net_shares() -> None:
    summary = form4_mod._form4_summary_rows(
        [{"acquiredDisposedCode": "X", "shares": 1000.0, "insider": "CEO",
          "filingDate": "2026-10-01"}]
    )
    assert summary["net_shares"] == 0
    assert "seller_count" not in summary


# ─── FORM4#5: Form 4 document URLs must be served from www.sec.gov ───────


def _adapter_with_filings(filings: list[dict[str, Any]]) -> Any:
    from showme.engine.data_sources.equity.sec_edgar_adapter import SECEdgarAdapter

    adapter = SECEdgarAdapter()

    async def fake_cik(_ticker: str) -> str:
        return "0000320193"

    async def fake_recent(_cik: str, *, form: str | None = None, limit: int = 40) -> list[dict[str, Any]]:
        return [dict(f) for f in filings][:limit]

    adapter.cik_for = fake_cik  # type: ignore[method-assign]
    adapter.recent_filings = fake_recent  # type: ignore[method-assign]
    return adapter


def test_form4_5_archive_document_url_is_on_www_sec_gov() -> None:
    adapter = _adapter_with_filings([
        {"accession": "0001140361-26-042149", "primaryDocument": "xslF345X06/form4.xml",
         "filingDate": "2026-10-01", "form": "4"},
    ])
    rows = asyncio.run(adapter.form4_filings("AAPL", limit=5))
    assert rows[0]["url"] == (
        "https://www.sec.gov/Archives/edgar/data/320193/000114036126042149/xslF345X06/form4.xml"
    )


def test_form4_5_fallback_index_url_is_on_www_sec_gov() -> None:
    adapter = _adapter_with_filings([{"accession": "", "primaryDocument": "", "form": "4"}])
    rows = asyncio.run(adapter.form4_filings("AAPL", limit=5))
    assert rows[0]["url"].startswith("https://www.sec.gov/cgi-bin/browse-edgar")


# ─── FORM4#6: months / transaction_types apply to the yfinance rows too ───


class _SEC:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    async def form4_filings(self, _ticker: str, *, limit: int = 40) -> list[dict[str, Any]]:
        return [dict(r) for r in self._rows][:limit]


def _yf_frame_relative() -> pd.DataFrame:
    """Two recent sales and one 400-day-old sale, dated relative to today."""
    now = datetime.now(timezone.utc)
    return pd.DataFrame(
        {
            "Shares": [1000, 2000, 3000],
            "Value": [100000.0, 200000.0, 300000.0],
            "URL": [None, None, None],
            "Text": ["Sale at price 100.00 per share."] * 3,
            "Insider": ["A", "B", "C"],
            "Position": ["Officer", "Officer", "Officer"],
            "Transaction": [None, None, None],
            "Start Date": pd.to_datetime([
                (now - timedelta(days=2)).date(),
                (now - timedelta(days=5)).date(),
                (now - timedelta(days=400)).date(),
            ]),
            "Ownership": ["D", "D", "D"],
        }
    )


def _execute_yf_and_sec(frame: pd.DataFrame, **params: Any) -> Any:
    deps = FunctionDeps()
    deps.yfinance = _YF(frame)
    deps.sec_edgar = _SEC([])
    fn = FORM4Function(deps)
    return asyncio.run(fn.execute(
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY), **params,
    ))


def test_form4_6_months_window_filters_yfinance_rows() -> None:
    res = _execute_yf_and_sec(_yf_frame_relative(), months=1)
    assert len(res.data["rows"]) == 2
    assert res.data["n"] == 2
    assert res.data["net_shares"] == pytest.approx(-3000.0)


def test_form4_6_transaction_types_filter_yfinance_rows() -> None:
    res = _execute_yf_and_sec(_yf_frame_relative(), months=24, transaction_types=["buy"])
    assert res.data["rows"] == []
    assert res.data["status"] == "empty"


# ─── FORM4#4: SEC-only filing metadata must not be labelled live_official ─


def _sec_adapter_row(days_ago: int) -> dict[str, Any]:
    """Shape the SEC adapter actually returns (``accession``, not ``accessionNumber``)."""
    filed = (datetime.now(timezone.utc) - timedelta(days=days_ago)).date().isoformat()
    return {
        "accession": "0001140361-26-042149",
        "filingDate": filed,
        "reportDate": filed,
        "form": "4",
        "primaryDocument": "xslF345X06/form4.xml",
        "primaryDocDescription": "FORM 4",
        "size": 1234,
        "isXBRL": 1,
        "url": "https://www.sec.gov/Archives/edgar/data/320193/000114036126042149/xslF345X06/form4.xml",
    }


def _execute_sec_only(rows: list[dict[str, Any]], **params: Any) -> Any:
    deps = FunctionDeps()
    deps.yfinance = None
    deps.sec_edgar = _SEC(rows)
    fn = FORM4Function(deps)
    return asyncio.run(fn.execute(
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY), **params,
    ))


def test_form4_4_sec_only_rows_are_metadata_not_live_official() -> None:
    res = _execute_sec_only([_sec_adapter_row(10)])
    assert res.data["data_mode"] != "live_official"
    assert res.data["status"] == "metadata_only"
    row = res.data["rows"][0]
    assert row["source_mode"] == "sec_form4_filing_metadata"
    assert row["accession"] == "0001140361-26-042149"
    assert row["filing_url"].startswith("https://www.sec.gov/Archives/")
    # Fields the filing list does not carry stay empty rather than being invented.
    assert row["filer"] is None
    assert row["shares"] is None
    assert row["transaction"] is None
    assert res.data["next_actions"]


def test_form4_4_sec_only_summary_does_not_report_a_net_flow() -> None:
    res = _execute_sec_only([_sec_adapter_row(10)])
    assert res.data.get("net_shares") is None
    assert res.data.get("net_notional") is None


# ─── FORM4#8: as_of is null without dated rows; windows are calendar months ─


def test_form4_8_summary_as_of_is_null_without_dated_rows() -> None:
    summary = form4_mod._form4_summary_rows([{"transaction": "Sale at price 1.00", "shares": 1.0}])
    assert summary["as_of"] is None


def test_form4_8_fallback_as_of_is_null_not_request_time() -> None:
    assert form4_mod._fallback_form4("AAPL")["as_of"] is None


def test_form4_8_six_month_window_is_calendar_not_186_days() -> None:
    # Six calendar months back is 181-184 days; 186 days back is outside it.
    now = datetime.now(timezone.utc)
    assert form4_mod._in_month_window(now - timedelta(days=186), 6) is False
    assert form4_mod._in_month_window(now - timedelta(days=120), 6) is True
