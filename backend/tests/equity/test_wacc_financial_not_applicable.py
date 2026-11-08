"""WACC#2 regression: financial issuers get an explicit not-applicable WACC.

A bank's or insurer's liabilities are operating funding (deposits, policy
reserves), so a book-debt capital-structure weight is meaningless. The
handler reports WACC as not applicable and keeps the cost of equity.
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
    api_key = "test-key"

    def __init__(self, by_series: dict[str, float]) -> None:
        self._by = by_series

    async def series(self, sid: str, frequency: str = "d"):
        value = self._by.get(sid)
        if value is None:
            return pd.DataFrame()
        return pd.DataFrame({"value": [value]})


def _instrument(symbol: str) -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


@pytest.mark.asyncio
async def test_financial_issuer_wacc_is_not_applicable_not_a_live_debt_weight():
    """JPM-like balance sheet: debt 1.34T vs equity 0.89T must NOT yield a live WACC."""
    raw = {
        "marketCap": 888_274_812_928.0,
        "totalDebt": 1_335_691_968_512.0,
        "sector": "Financial Services",
        "industry": "Banks - Diversified",
    }
    deps = FunctionDeps(
        yfinance=_FakeYf(raw=raw),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}),
    )
    res = await WACCFunction(deps).execute(instrument=_instrument("JPM"), beta=1.1)
    data = res.data
    assert data["status"] == "not_applicable"
    assert data["wacc"] is None
    assert data["debt_weight"] is None
    assert data["equity_weight"] is None
    assert data["capital_structure_data_state"] == "not_applicable_financial"
    assert data["debt_value_source"] == "not_applicable_financial"
    # Cost of equity is still a valid CAPM output and stays reported.
    assert data["re_capm"] == pytest.approx(4.0 / 100 + 1.1 * 0.05, abs=1e-9)
    assert any("bank" in w.lower() or "financial" in w.lower() for w in res.warnings)
    assert data["reason"]


@pytest.mark.asyncio
async def test_financial_issuer_without_balance_sheet_is_not_applicable_too():
    raw = {"marketCap": 0.0, "totalDebt": 0.0, "sector": "Financial Services", "industry": "Insurance - Life"}
    deps = FunctionDeps(yfinance=_FakeYf(raw=raw), fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}))
    res = await WACCFunction(deps).execute(instrument=_instrument("INS"), beta=1.0)
    assert res.data["status"] == "not_applicable"
    assert res.data["wacc"] is None


@pytest.mark.asyncio
async def test_non_financial_issuer_still_computes_wacc_from_book_debt():
    raw = {"marketCap": 300.0, "totalDebt": 100.0, "sector": "Consumer Cyclical"}
    deps = FunctionDeps(yfinance=_FakeYf(raw=raw), fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.0}))
    res = await WACCFunction(deps).execute(instrument=_instrument("CC"), beta=1.0)
    assert res.data["status"] == "ok"
    assert res.data["wacc"] is not None
    assert res.data["debt_weight"] == pytest.approx(0.25, abs=1e-9)
