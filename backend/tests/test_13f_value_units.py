"""13F value units are resolved per reporting period (HDS#4 follow-up).

Form 13F InfoTable values were reported in thousands of dollars for periods
before the SEC switched the table to whole dollars. The adapter used to
multiply every period by 1000, which overstated recent filings 1000x and put
that figure into HDS market_value. The unit is now resolved from report_date:

* report_date before 2022-12-31 -> thousands, value_usd = SUM(value_x1000) * 1000
* report_date after 2022-12-31  -> whole dollars, value_usd = SUM(value_x1000)
* 2022-12-31 or no report_date  -> unit unresolved, value_usd is NULL

Network is not used: a DuckDB file is written under tmp_path.
"""
from __future__ import annotations

import asyncio

import duckdb
import pandas as pd
import pytest

from showme.engine.data_sources.equity import sec_13f_adapter


@pytest.fixture()
def holdings_db(tmp_path, monkeypatch):
    db = tmp_path / "sec_13f.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""CREATE TABLE holdings (
        filer_cik TEXT, accession TEXT, report_date TEXT,
        issuer TEXT, cusip TEXT, value_x1000 DOUBLE, shares DOUBLE, share_type TEXT)""")
    con.execute("""INSERT INTO holdings VALUES
        ('0000000001', 'a1', '2022-09-30', 'APPLE INC', '037833100', 1000, 10, 'SH'),
        ('0000000002', 'a2', '2026-06-30', 'APPLE INC', '037833100', 1000000, 20, 'SH'),
        ('0000000003', 'a3', '2022-12-31', 'APPLE INC', '037833100', 500, 5, 'SH'),
        ('0000000004', 'a4', '', 'APPLE INC', '037833100', 700, 7, 'SH')""")
    con.close()
    monkeypatch.setattr(sec_13f_adapter, "_db_path", lambda: db)
    return db


def _values_by_filer(df):
    return {row["filer_cik"]: row["value_usd"] for _, row in df.iterrows()}


def test_pre_2023_period_is_thousands_and_scaled_once(holdings_db):
    adapter = sec_13f_adapter.SEC13FAdapter()
    df = asyncio.run(adapter.query_holdings_by_security(issuer_normalized="APPLEINC", top_n=10))
    values = _values_by_filer(df)
    assert values["0000000001"] == 1_000_000.0


def test_post_2022_period_is_whole_dollars_not_scaled(holdings_db):
    adapter = sec_13f_adapter.SEC13FAdapter()
    df = asyncio.run(adapter.query_holdings_by_security(issuer_normalized="APPLEINC", top_n=10))
    values = _values_by_filer(df)
    # 1,000,000 reported dollars, not 1,000,000,000.
    assert values["0000000002"] == 1_000_000.0


def test_ambiguous_or_missing_period_has_no_dollar_value(holdings_db):
    adapter = sec_13f_adapter.SEC13FAdapter()
    df = asyncio.run(adapter.query_holdings_by_security(issuer_normalized="APPLEINC", top_n=10))
    values = _values_by_filer(df)
    assert pd.isna(values["0000000003"])
    assert pd.isna(values["0000000004"])
