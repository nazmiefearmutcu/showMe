"""WACC#2 follow-up: DCF and DDM must never substitute a constant 8% WACC.

When WACC is not applicable (financial issuer, wacc None) or the WACC
provider failed, DCF and DDM report an explicit state with a reason and
next actions. They do not discount at a silent 0.08.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DCFFunction, DDMFunction
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


_JPM_RAW = {
    "marketCap": 888_274_812_928.0,
    "totalDebt": 1_335_691_968_512.0,
    "sector": "Financial Services",
    "industry": "Banks - Diversified",
}


def _jpm_deps() -> FunctionDeps:
    return FunctionDeps(
        yfinance=_FakeYf(raw=_JPM_RAW),
        fred=_FakeFred({"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}),
    )


@pytest.mark.asyncio
async def test_ddm_financial_issuer_without_required_return_is_not_valued_at_8pct():
    res = await DDMFunction(_jpm_deps()).execute(
        _instrument("JPM"), dividend_ttm=2.0, growth_rate=0.03
    )
    data = res.data
    assert data["status"] == "not_applicable"
    assert data.get("fair_value_per_share") is None
    assert data.get("required_return") is None
    assert data["reason"]
    assert data["next_actions"]
    assert all(v != 0.08 for v in (data.get("required_return"),))
    assert any("wacc" in w.lower() for w in res.warnings)


@pytest.mark.asyncio
async def test_dcf_financial_issuer_without_wacc_is_not_valued_at_8pct():
    res = await DCFFunction(_jpm_deps()).execute(
        _instrument("JPM"), fcfe=100.0, shares_outstanding=10.0
    )
    data = res.data
    assert data["status"] == "not_applicable"
    assert data["wacc"] is None
    assert data.get("fair_value_per_share") is None
    assert data.get("equity_value") is None
    assert data["reason"]
    assert data["next_actions"]


@pytest.mark.asyncio
async def test_dcf_wacc_provider_failure_is_not_replaced_by_constant(monkeypatch):
    async def boom(self, instrument=None, **params):
        raise RuntimeError("wacc provider down")

    monkeypatch.setattr(WACCFunction, "execute", boom)
    res = await DCFFunction(_jpm_deps()).execute(
        _instrument("AAPL"), fcfe=100.0, shares_outstanding=10.0
    )
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None
    assert res.data.get("fair_value_per_share") is None
    assert any("wacc" in w.lower() for w in res.warnings)


@pytest.mark.asyncio
async def test_ddm_wacc_provider_failure_is_not_replaced_by_constant(monkeypatch):
    async def boom(self, instrument=None, **params):
        raise RuntimeError("wacc provider down")

    monkeypatch.setattr(WACCFunction, "execute", boom)
    res = await DDMFunction(_jpm_deps()).execute(
        _instrument("AAPL"), dividend_ttm=2.0, growth_rate=0.03
    )
    assert res.data["status"] == "provider_unavailable"
    assert res.data.get("fair_value_per_share") is None
    assert res.data.get("required_return") is None


@pytest.mark.asyncio
async def test_explicit_inputs_still_value_normally():
    deps = _jpm_deps()
    dcf = await DCFFunction(deps).execute(
        _instrument("JPM"), fcfe=100.0, shares_outstanding=10.0, wacc=0.10,
        growth_terminal=0.02, years=3,
    )
    assert dcf.data["status"] == "ok"
    # DCFS#2: the caller rate is the discount rate applied to FCFE; "wacc" is the
    # WACC model reference value (null when the caller set the rate).
    assert dcf.data["discount_rate"] == pytest.approx(0.10)
    ddm = await DDMFunction(deps).execute(
        _instrument("JPM"), dividend_ttm=2.0, required_return=0.10, growth_rate=0.03
    )
    assert ddm.data["status"] == "ok"
    assert ddm.data["required_return"] == pytest.approx(0.10)
