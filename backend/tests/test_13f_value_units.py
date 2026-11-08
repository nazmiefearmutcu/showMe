"""13F InfoTable value unit is unresolved, so the adapter derives no dollar value.

Form 13F InfoTable <value> entries are stored raw in ``value_x1000``. Whether
they are thousands of dollars or whole dollars depends on the filing date
(the SEC changed the table format around the start of 2023), and the local
store keeps only ``report_date``. Neither reading can be confirmed offline,
so the adapter must not scale or pick a unit. Its contract is:

* ``value_usd`` is always NULL (no dollar figure is invented),
* ``value_as_reported`` is the raw SUM of the stored InfoTable values,
* ``value_unit`` is ``'unresolved'``,
* rows are ranked by shares, not by a value that mixes units.

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
        ('0000000004', 'a4', '', 'APPLE INC', '037833100', 700, 7, 'SH'),
        ('0000000005', 'a5', '2026-06-30', 'APPLE INC', '037833100', 50, 900, 'SH')""")
    con.close()
    monkeypatch.setattr(sec_13f_adapter, "_db_path", lambda: db)
    return db


def _query(issuer="APPLEINC", top_n=10) -> pd.DataFrame:
    adapter = sec_13f_adapter.SEC13FAdapter()
    return asyncio.run(adapter.query_holdings_by_security(issuer_normalized=issuer, top_n=top_n))


def _by_filer(df: pd.DataFrame) -> dict[str, pd.Series]:
    return {row["filer_cik"]: row for _, row in df.iterrows()}


@pytest.mark.parametrize("filer", ["0000000001", "0000000002", "0000000003", "0000000004"])
def test_dollar_value_is_never_derived_for_any_period(holdings_db, filer):
    rows = _by_filer(_query())
    assert pd.isna(rows[filer]["value_usd"]), rows[filer]


def test_raw_reported_value_is_exposed_unscaled_and_labelled_unresolved(holdings_db):
    rows = _by_filer(_query())
    assert rows["0000000001"]["value_as_reported"] == 1000.0
    assert rows["0000000002"]["value_as_reported"] == 1_000_000.0
    assert rows["0000000003"]["value_as_reported"] == 500.0
    assert all(v == "unresolved" for v in _query()["value_unit"])


def test_rows_are_ranked_by_shares_not_by_mixed_unit_values(holdings_db):
    df = _query()
    # Filer 5 has the smallest raw value but the most shares; it must rank first.
    assert list(df["filer_cik"])[0] == "0000000005", df


def test_top_n_limits_rows(holdings_db):
    assert len(_query(top_n=2)) == 2
