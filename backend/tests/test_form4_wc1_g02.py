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
