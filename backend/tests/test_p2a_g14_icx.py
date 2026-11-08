"""P2A G14 — ICX states coverage honestly and serves full sector membership.

ICX#1: the curated index tables are subsets (NDX 29 of 100, DAX 10 of 40, ...)
but returned status "ok". A subset is now status "partial" with coverage.
ICX#2: sector tables held 5-10 hand-picked names per sector although the
bundled security master covers all 503 S&P 500 names with a sector.
"""
from __future__ import annotations

import asyncio
from collections import Counter

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.screen import icx as icx_mod
from showme.engine.functions.screen._funcs import _load_security_master
from showme.engine.functions.screen.icx import ICXFunction


def _run(**params):
    return asyncio.run(ICXFunction(FunctionDeps()).execute(quotes="0", **params))


def _master_sector_counts() -> Counter:
    label = {"Technology": "Information Technology"}
    symbols = icx_mod._load_sp500_symbols()
    master = {str(r["symbol"]).upper(): r for r in _load_security_master()}
    return Counter(label.get(str(master[s]["sector"]), str(master[s]["sector"]))
                   for s in symbols if s in master)


# ---- ICX#1: partial index tables are flagged, not served as complete -------

def test_dax_subset_is_partial_with_coverage() -> None:
    res = _run(index="DAX")
    data = res.data
    assert data["status"] == "partial"
    assert data["coverage"] == {"listed": 10, "official": 40, "complete": False}
    assert any("10 of 40" in w for w in res.warnings)


def test_ndx_subset_is_partial_with_coverage() -> None:
    data = _run(index="NDX").data
    assert data["status"] == "partial"
    assert data["coverage"]["listed"] == data["constituents"] == 29
    assert data["coverage"]["official"] == 100


def test_complete_index_table_stays_ok() -> None:
    data = _run(index="DJIA").data
    assert data["coverage"] == {"listed": 30, "official": 30, "complete": True}
    assert data["status"] == "ok"


def test_partial_index_summary_does_not_claim_full_index() -> None:
    res = _run(index="FTSE")
    assert res.data["status"] == "partial"
    assert res.data["summary"]["constituent_count"] == 10


# ---- ICX#2: sector view serves the full S&P 500 membership -----------------

def test_sector_view_lists_every_sp500_name_in_the_sector() -> None:
    expected = _master_sector_counts()["Information Technology"]
    res = _run(sector="Information Technology")
    data = res.data
    assert data["status"] == "ok"
    assert len(data["rows"]) == expected
    assert expected > 10
    symbols = {r["symbol"] for r in data["rows"]}
    assert {"AAPL", "MSFT", "NVDA"} <= symbols
    assert "showme_security_master" in res.sources
    assert "showme_gics_reference" not in res.sources


def test_every_sp500_name_appears_in_exactly_one_sector() -> None:
    sectors = _master_sector_counts()
    total = sum(sectors.values())
    assert total == len(icx_mod._load_sp500_symbols()) == 503
    listed = 0
    for sector in sectors:
        listed += len(_run(sector=sector).data["rows"])
    assert listed == total


def test_curated_sub_industry_is_kept_where_available() -> None:
    rows = {r["symbol"]: r for r in _run(sector="Information Technology").data["rows"]}
    assert rows["AAPL"]["sub_industry"] == "Technology Hardware, Storage & Peripherals"


def test_missing_security_master_never_serves_partial_sector_as_full(monkeypatch, tmp_path) -> None:
    # Missing master: _read_security_master silently returns the 13-row fallback.
    # The sector must not be presented as the full S&P 500 membership.
    from showme.engine.functions.screen import _funcs

    monkeypatch.setattr(_funcs, "_SECURITY_MASTER_PATH", tmp_path / "missing_master.json")
    monkeypatch.setattr(_funcs, "_SECURITY_MASTER_CACHE", None)
    res = _run(sector="Information Technology")
    data = res.data
    assert data["status"] == "partial"
    assert data["coverage"] == {
        "listed": len(data["rows"]), "official": None, "complete": False,
    }
    assert data["summary"]["coverage"] == data["coverage"]
    assert "showme_gics_reference" in res.sources
    assert "showme_security_master" not in res.sources
    assert len(data["rows"]) == len(icx_mod._SECTOR_CONSTITUENTS["Information Technology"])
