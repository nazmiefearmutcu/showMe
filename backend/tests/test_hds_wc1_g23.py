"""HDS holder-table fixes (wc1-g23): HDS#2 percent-of-outstanding mapping,
HDS#6 holder_type filter. Network is patched: no provider is called.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pandas as pd

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import hds

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Yahoo:
    """Serves the yfinance holder tables with their real column names."""

    def __init__(self, institutional: pd.DataFrame, mutualfund: pd.DataFrame | None = None) -> None:
        self.payload = {
            "major": pd.DataFrame(),
            "institutional": institutional,
            "mutualfund": mutualfund if mutualfund is not None else pd.DataFrame(),
        }

    async def fetch(self, request: Any) -> Any:
        return self.payload


class _Sec13F:
    async def query_holdings_by_security(self, **_kwargs: Any) -> pd.DataFrame:
        return pd.DataFrame()


def _fn(**deps: Any) -> hds.HDSFunction:
    base: dict[str, Any] = {"yfinance": None, "sec_13f": None, "sec_edgar": None}
    base.update(deps)
    return hds.HDSFunction(SimpleNamespace(**base))


def _run(fn: hds.HDSFunction, **params: Any):
    return asyncio.run(fn.execute(instrument=AAPL, live=True, **params))


def _institutional_frame() -> pd.DataFrame:
    # yfinance 1.3 keeps the Yahoo column name pctHeld (fraction of shares outstanding).
    return pd.DataFrame({
        "Date Reported": [pd.Timestamp("2026-03-31"), pd.Timestamp("2026-03-31")],
        "Holder": ["Vanguard Group, Inc.", "BlackRock, Inc."],
        "pctHeld": [0.0800, 0.0660],
        "Shares": [1_300_000_000, 1_080_000_000],
        "Value": [250_000_000_000, 210_000_000_000],
    })


def _mutualfund_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Date Reported": [pd.Timestamp("2026-03-31")],
        "Holder": ["Vanguard Total Stock Market Index"],
        "pctHeld": [0.0300],
        "Shares": [500_000_000],
        "Value": [90_000_000_000],
    })


# HDS#2 ---------------------------------------------------------------------

def test_yfinance_pctheld_maps_to_pct_outstanding_fraction():
    res = _run(_fn(yfinance=_Yahoo(_institutional_frame()), sec_13f=_Sec13F(), sec_edgar=None))
    rows = res.data["rows"]
    assert rows, res.data
    # RED before fix: pct_outstanding was None because only "% Out" was read.
    assert rows[0]["pct_outstanding"] == 0.08, rows[0]
    assert rows[1]["pct_outstanding"] == 0.066, rows[1]
    assert all(0 <= r["pct_outstanding"] <= 1 for r in rows)


# HDS#6 ---------------------------------------------------------------------

def test_holder_type_mutual_fund_restricts_rows():
    fn = _fn(yfinance=_Yahoo(_institutional_frame(), _mutualfund_frame()), sec_13f=_Sec13F(), sec_edgar=None)
    res = _run(fn, holder_type="mutual_fund")
    types = {r["holder_type"] for r in res.data["rows"]}
    # RED before fix: holder_type was declared in the manifest but never applied.
    assert types == {"mutual_fund"}, res.data["rows"]
    assert res.data["holder_type_filter"] == "mutual_fund"


def test_holder_type_institutional_excludes_mutual_fund_rows():
    fn = _fn(yfinance=_Yahoo(_institutional_frame(), _mutualfund_frame()), sec_13f=_Sec13F(), sec_edgar=None)
    res = _run(fn, holder_type="institutional")
    assert res.data["rows"] and all(r["holder_type"] == "institutional" for r in res.data["rows"])


def test_holder_type_insider_is_explicitly_unavailable_not_all_rows():
    fn = _fn(yfinance=_Yahoo(_institutional_frame(), _mutualfund_frame()), sec_13f=_Sec13F(), sec_edgar=None)
    res = _run(fn, holder_type="insider")
    assert res.data["rows"] == []
    assert res.data["status"] == "provider_unavailable"
    assert "insider" in res.data["reason"].lower()


def test_unknown_holder_type_is_input_error():
    fn = _fn(yfinance=_Yahoo(_institutional_frame()), sec_13f=_Sec13F(), sec_edgar=None)
    res = _run(fn, holder_type="whales")
    assert res.data["status"] == "input_error"
    assert res.data["rows"] == []
