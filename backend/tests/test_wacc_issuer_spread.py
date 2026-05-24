"""Audit Q3 #16 / #17 / #18 — WACC cost-of-debt provenance & sector
default + balance-sheet sources.

Pinned behaviors:
  * `rd_source = "issuer_implied"` when both `interestExpense` and
    `totalDebt` are present in yfinance fundamentals.
  * `rd_source = "fred_bbb"` when BAMLC0A4CBBB is the chosen FRED series
    (was AAA, which understates 100-300 bp).
  * `debt_value_source = "book"` when balance sheet has totalDebt > 0.
  * Sector-aware E/D fallback when totalDebt and marketCap both missing:
    bank → 0.1/0.9, tech → 0.95/0.05, utility → 0.45/0.55.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.wacc import WACCFunction


@dataclass
class _RefdataPayload:
    market_cap: float | None = None
    country: str | None = "US"
    extras: dict | None = None


class _FakeYf:
    def __init__(self, *, raw: dict[str, Any]) -> None:
        self._raw = raw

    async def fetch(self, request):
        from showme.engine.core.base_data_source import DataKind
        if request.kind == DataKind.REFDATA:
            return _RefdataPayload(
                market_cap=self._raw.get("marketCap"),
                country=self._raw.get("country", "US"),
                extras={"raw": dict(self._raw)},
            )
        raise NotImplementedError


class _FakeFred:
    def __init__(self, by_series: dict[str, float]) -> None:
        self._by = by_series

    async def series(self, sid: str, frequency: str = "d"):
        value = self._by.get(sid)
        if value is None:
            return pd.DataFrame()
        return pd.DataFrame({"value": [value]})


@pytest.mark.asyncio
async def test_rd_uses_issuer_implied_when_balance_sheet_present():
    raw = {
        "marketCap": 100.0,
        "totalDebt": 25.0,
        "interestExpense": 1.5,  # implied rd = 6%
        "sector": "Technology",
    }
    deps = FunctionDeps(
        yfinance=_FakeYf(raw=raw),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBB": 6.5, "AAA": 4.8}),
    )
    fn = WACCFunction(deps)
    instrument = Instrument(symbol="ACME", asset_class=AssetClass.EQUITY)
    res = await fn.execute(instrument=instrument, beta=1.1)
    data = res.data
    # Implied debt cost (1.5 / 25 = 0.06)
    assert abs(data["rd"] - 0.06) < 1e-9
    assert data["rd_source"] == "issuer_implied"
    assert data["debt_value_source"] == "book"
    assert data["capital_structure_data_state"] == "live"


@pytest.mark.asyncio
async def test_rd_falls_back_to_fred_bbb_not_aaa():
    raw = {
        "marketCap": 100.0,
        "totalDebt": 25.0,
        # no interestExpense → fall through to FRED
        "sector": "Technology",
    }
    deps = FunctionDeps(
        yfinance=_FakeYf(raw=raw),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBB": 6.5, "AAA": 4.8}),
    )
    fn = WACCFunction(deps)
    instrument = Instrument(symbol="ACME", asset_class=AssetClass.EQUITY)
    res = await fn.execute(instrument=instrument, beta=1.1)
    data = res.data
    # BBB = 6.5% / 100 = 0.065, not AAA 0.048
    assert abs(data["rd"] - 0.065) < 1e-9
    assert data["rd_source"] == "fred_bbb"


@pytest.mark.asyncio
async def test_sector_default_kicks_in_for_bank_without_balance_sheet():
    raw = {
        "marketCap": 0.0,
        "totalDebt": 0.0,
        "sector": "Banks - Diversified",
    }
    deps = FunctionDeps(
        yfinance=_FakeYf(raw=raw),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBB": 6.5}),
    )
    fn = WACCFunction(deps)
    instrument = Instrument(symbol="BNK", asset_class=AssetClass.EQUITY)
    res = await fn.execute(instrument=instrument, beta=1.0)
    data = res.data
    assert abs(data["equity_weight"] - 0.1) < 1e-9
    assert abs(data["debt_weight"] - 0.9) < 1e-9
    assert data["debt_value_source"] == "sector_default_financial"
    assert data["capital_structure_data_state"] == "sector_default"


@pytest.mark.asyncio
async def test_sector_default_tech_uses_high_equity_share():
    raw = {
        "marketCap": 0.0,
        "totalDebt": 0.0,
        "sector": "Technology",
    }
    deps = FunctionDeps(
        yfinance=_FakeYf(raw=raw),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBB": 6.5}),
    )
    fn = WACCFunction(deps)
    instrument = Instrument(symbol="TEC", asset_class=AssetClass.EQUITY)
    res = await fn.execute(instrument=instrument, beta=1.2)
    data = res.data
    assert abs(data["equity_weight"] - 0.95) < 1e-9
    assert data["debt_value_source"] == "sector_default_tech"
