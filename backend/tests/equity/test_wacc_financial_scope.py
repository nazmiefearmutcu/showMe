"""WACC#2 scope: only banks and insurers are not_applicable.

yfinance reports card networks, exchanges and asset managers under the
sector "Financial Services" too. Those issuers carry ordinary capital
structures, so their WACC must stay a live book-weight result rather than
being labelled not applicable.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.wacc import WACCFunction


class _Damo:
    """Live-cache ERP stub (5.0%): these tests exercise other WACC inputs."""

    async def get_erp_with_source(self, country="US"):
        return 0.05, "damodaran_cache"


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


def _run(raw: dict[str, Any], symbol: str):
    deps = FunctionDeps(damodaran=_Damo(), 
        yfinance=_FakeYf(raw=raw),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}),
    )
    return WACCFunction(deps).execute(instrument=_instrument(symbol), beta=1.0)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "industry",
    [
        "Credit Services",
        "Financial Data & Stock Exchanges",
        "Asset Management",
        "Insurance Brokers",
    ],
)
async def test_non_bank_non_insurer_financials_keep_a_live_wacc(industry):
    raw = {
        "marketCap": 500.0,
        "totalDebt": 20.0,
        "sector": "Financial Services",
        "industry": industry,
    }
    res = await _run(raw, "NONBANK")
    data = res.data
    assert data["status"] == "ok", data
    assert data["wacc"] is not None
    assert data["capital_structure_data_state"] == "live"
    assert data["debt_value_source"] == "book"
    assert data["debt_weight"] == pytest.approx(20.0 / 520.0, abs=1e-9)


@pytest.mark.asyncio
async def test_bank_industry_still_not_applicable():
    raw = {
        "marketCap": 888.0,
        "totalDebt": 1336.0,
        "sector": "Financial Services",
        "industry": "Banks - Regional",
    }
    res = await _run(raw, "BANK")
    assert res.data["status"] == "not_applicable"
    assert res.data["wacc"] is None
