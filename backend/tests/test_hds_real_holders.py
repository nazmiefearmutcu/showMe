"""HDS never invents holders (data policy, p1a-g02).

Covers HDS#1 (model rows returned for any symbol), HDS#3 (Yahoo major-holder
summary emitted as holder rows) and HDS#4 (13F lookup never matches a ticker
and drops the returned field names). Network is patched: no provider is
called.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import duckdb
import pandas as pd

from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.data_sources.equity import sec_13f_adapter
from showme.engine.functions.equity import hds

ZZZQ = Instrument(symbol="ZZZQ", asset_class=AssetClass.EQUITY)
AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Failing:
    async def fetch(self, request: Any) -> Any:
        raise RuntimeError("provider down")


class _Yahoo:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def fetch(self, request: Any) -> Any:
        return self.payload


class _SecEdgar:
    def __init__(self, cik: str | None, name: str | None = None) -> None:
        self._cik = cik
        self._name = name

    async def cik_for(self, ticker: str) -> str | None:
        return self._cik

    async def submissions(self, cik: str) -> dict[str, Any]:
        return {"name": self._name}


class _Sec13F:
    def __init__(self, frame: pd.DataFrame | None = None) -> None:
        self.frame = frame if frame is not None else pd.DataFrame()
        self.calls: list[dict[str, Any]] = []

    async def query_holdings_by_security(self, **kwargs: Any) -> pd.DataFrame:
        self.calls.append(kwargs)
        return self.frame


def _fn(**deps: Any) -> hds.HDSFunction:
    base: dict[str, Any] = {"yfinance": None, "sec_13f": None, "sec_edgar": None}
    base.update(deps)
    return hds.HDSFunction(SimpleNamespace(**base))


def _run(fn: hds.HDSFunction, instrument: Instrument, **params: Any):
    return asyncio.run(fn.execute(instrument=instrument, **params))


def _major_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {"Value": [0.01655, 0.66596, 0.67717, 7748]},
        index=["insidersPercentHeld", "institutionsPercentHeld",
               "institutionsFloatPercentHeld", "institutionsCount"],
    )


def _institutional_frame() -> pd.DataFrame:
    return pd.DataFrame({
        "Holder": ["Vanguard Group, Inc."],
        "Shares": [1_300_000_000],
        "Date Reported": [pd.Timestamp("2026-06-30")],
        "% Out": [0.087],
        "Value": [250_000_000_000],
    })


# HDS#1 ---------------------------------------------------------------------

def test_live_off_returns_no_invented_holder_rows():
    res = _run(_fn(), ZZZQ)  # live not requested -> handler default
    assert res.data["rows"] == [], res.data
    assert res.data["status"] == "needs_input"
    assert "live" in res.data["reason"].lower()
    assert res.sources == []


def test_live_on_with_all_providers_down_is_unavailable_not_reference_rows():
    fn = _fn(yfinance=_Failing(), sec_13f=_Sec13F(), sec_edgar=_SecEdgar(None))
    res = _run(fn, AAPL, live=True)
    assert res.data["status"] == "provider_unavailable", res.data
    assert res.data["rows"] == []
    assert "holders_reference" not in res.sources


# HDS#3 ---------------------------------------------------------------------

def test_major_holder_summary_is_not_emitted_as_holder_rows():
    yahoo = _Yahoo({
        "major": _major_frame(),
        "institutional": _institutional_frame(),
        "mutualfund": pd.DataFrame(),
        "insider_transactions": pd.DataFrame(),
    })
    res = _run(_fn(yfinance=yahoo), AAPL, live=True)
    holders = [r["holder"] for r in res.data["rows"]]
    assert holders == ["Vanguard Group, Inc."], holders
    assert "insidersPercentHeld" not in holders
    summary = res.data["major_holders_summary"]
    assert summary["institutionsCount"] == 7748
    assert summary["insidersPercentHeld"] == 0.01655


# HDS#4 ---------------------------------------------------------------------

def test_13f_lookup_resolves_ticker_to_issuer_and_keeps_fields():
    frame = pd.DataFrame({
        "filer_cik": ["0000102909"],
        "report_date": ["2026-06-30"],
        "value_usd": [None],  # adapter: unit unresolved, so no dollar value
        "value_as_reported": [5.0e9],
        "value_unit": ["unresolved"],
        "shares": [2.5e7],
    })
    sec13f = _Sec13F(frame)
    fn = _fn(sec_13f=sec13f, sec_edgar=_SecEdgar("0000320193", "Apple Inc."))
    res = _run(fn, AAPL, live=True)
    assert sec13f.calls, "13F query was never made"
    call = sec13f.calls[0]
    assert call.get("issuer_normalized") == "APPLEINC", call
    assert call.get("issuer") in (None, ""), call
    row = res.data["rows"][0]
    # The InfoTable unit is unresolved, so the raw 13F value is never shown as dollars.
    assert row["market_value"] is None
    assert row["market_value_status"] == "unit_unresolved"
    assert row["shares"] == 2.5e7
    assert row["quarter"] == "2026-06-30"
    assert row["holder"] == "CIK 0000102909"
    assert res.sources == ["sec_13f"]


def test_13f_handler_never_passes_a_dollar_value_through():
    # Even if a source supplied a dollar-looking value_usd, the handler does not
    # present it: the 13F InfoTable unit is unresolved.
    frame = pd.DataFrame({
        "filer_cik": ["0000102909"],
        "report_date": ["2026-06-30"],
        "value_usd": [5.0e9],
        "shares": [2.5e7],
    })
    fn = _fn(sec_13f=_Sec13F(frame), sec_edgar=_SecEdgar("0000320193", "Apple Inc."))
    res = _run(fn, AAPL, live=True)
    assert res.data["rows"][0]["market_value"] is None
    assert res.data["rows"][0]["shares"] == 2.5e7


def test_13f_unknown_ticker_is_reported_not_guessed():
    sec13f = _Sec13F()
    fn = _fn(sec_13f=sec13f, sec_edgar=_SecEdgar(None))
    res = _run(fn, ZZZQ, live=True)
    assert sec13f.calls == []
    assert res.data["rows"] == []
    assert any("ZZZQ" in w for w in res.metadata["provider_errors"])


def test_adapter_exact_normalized_issuer_match(tmp_path, monkeypatch):
    db = tmp_path / "sec_13f.duckdb"
    con = duckdb.connect(str(db))
    con.execute("""CREATE TABLE holdings (
        filer_cik TEXT, accession TEXT, report_date TEXT,
        issuer TEXT, cusip TEXT, value_x1000 DOUBLE, shares DOUBLE, share_type TEXT)""")
    con.execute("""INSERT INTO holdings VALUES
        ('0000000001', 'a1', '2026-06-30', 'APPLE INC', '037833100', 1000, 10, 'SH'),
        ('0000000002', 'a2', '2026-06-30', 'APPLE HOSPITALITY REIT', '03784Y200', 500, 5, 'SH')""")
    con.close()
    monkeypatch.setattr(sec_13f_adapter, "_db_path", lambda: db)
    adapter = sec_13f_adapter.SEC13FAdapter()
    df = asyncio.run(adapter.query_holdings_by_security(issuer_normalized="APPLEINC", top_n=10))
    assert list(df["filer_cik"]) == ["0000000001"], df
