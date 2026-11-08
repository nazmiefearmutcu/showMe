"""HFS#2: the holder-search inputs must be honoured or refused, never ignored.

* quarter=YYYY-Q# used to match nothing: the store keeps report_date as a SEC
  period date (2026-06-30), and the adapter filtered with LIKE 'YYYY-Q#%'.
* With no quarter, rows from every ingested report date were ranked together
  and labelled quarter='latest'.
* filer_type was declared in the seed but never read, so filer_type=hedge_fund
  returned unfiltered rows (the local store holds no filer classification).

These tests run the real SEC 13F adapter SQL against a temporary DuckDB store
(no network).
"""

from __future__ import annotations

import asyncio

import duckdb
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity import sec_13f_adapter
from showme.engine.functions.equity.hfs import HFSFunction


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
        ('0000000005', 'a5', '2026-06-30', 'APPLE INC', '037833100', 50, 900, 'SH')""")
    con.close()
    monkeypatch.setattr(sec_13f_adapter, "_db_path", lambda: db)
    return db


def _run(**params):
    deps = FunctionDeps()
    deps.sec_13f = sec_13f_adapter.SEC13FAdapter()
    return asyncio.run(HFSFunction(deps).execute(issuer="APPLE", **params))


def _dates(res) -> set[str]:
    return {str(r["report_date"]) for r in res.data["rows"]}


def test_quarter_input_selects_that_quarter_only(holdings_db) -> None:
    res = _run(quarter="2026-Q2")
    assert res.data["status"] == "ok", res.data
    assert _dates(res) == {"2026-06-30"}
    assert len(res.data["rows"]) == 2
    assert res.data["quarter"] == "2026-Q2"


def test_quarter_with_no_store_rows_says_so_for_that_quarter(holdings_db) -> None:
    res = _run(quarter="2024-Q4")
    assert res.data["rows"] == []
    assert res.data["status"] == "provider_unavailable"
    assert "2024-Q4" in res.data["reason"]


def test_malformed_quarter_is_an_input_error_not_a_silent_miss(holdings_db) -> None:
    res = _run(quarter="2026Q2")
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "quarter"
    assert res.data["rows"] == []


def test_no_quarter_does_not_label_mixed_report_dates_as_latest(holdings_db) -> None:
    res = _run()
    assert _dates(res) == {"2022-09-30", "2022-12-31", "2026-06-30"}
    assert res.data["quarter"] != "latest"
    assert any("report dates" in w for w in res.warnings), res.warnings


def test_filer_type_other_than_all_is_refused_not_ignored(holdings_db) -> None:
    res = _run(filer_type="hedge_fund")
    assert res.data["status"] == "input_error"
    assert res.data["field"] == "filer_type"
    assert res.data["rows"] == []
    assert "does not classify filers" in res.data["reason"]


def test_filer_type_all_is_accepted(holdings_db) -> None:
    res = _run(filer_type="all", quarter="2026-Q2")
    assert res.data["status"] == "ok"
    assert len(res.data["rows"]) == 2


def test_top_n_limits_rows(holdings_db) -> None:
    res = _run(quarter="2026-Q2", top_n=1)
    assert len(res.data["rows"]) == 1
    assert res.data["rows"][0]["shares"] == 900


def test_cusip_is_not_narrowed_by_the_bound_ticker(holdings_db) -> None:
    # cusip takes precedence over the symbol (hfs_seed). The bound ticker must
    # not also filter the CUSIP rows: "AAPL" does not occur in the issuer name.
    deps = FunctionDeps()
    deps.sec_13f = sec_13f_adapter.SEC13FAdapter()
    res = asyncio.run(HFSFunction(deps).execute(
        instrument=Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY),
        cusip="037833100", quarter="2026-Q2",
    ))
    assert res.data["status"] == "ok", res.data
    assert len(res.data["rows"]) == 2
    assert _dates(res) == {"2026-06-30"}
