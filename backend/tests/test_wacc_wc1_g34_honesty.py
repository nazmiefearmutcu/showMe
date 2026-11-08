"""WACC honesty regressions (wc1-g34): T10, WACC#3, WACC#4, WACC#6.

No input may be a silent constant. A missing market input (beta, risk-free
rate, cost of debt, capital-structure weights) makes WACC an explicit
provider_unavailable state with reason and next_actions; the components
that are real stay reported. Labelled model assumptions (ERP default, the
statutory tax rate) keep status ok but set data_state to "partial".
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import wacc as wacc_mod
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


class _FakeDamodaran:
    """Stands in for DamodaranAdapter; returns (erp, source) like get_erp_with_source."""

    def __init__(self, erp: float = 0.046, source: str = "damodaran_cache") -> None:
        self._erp, self._source = erp, source

    async def get_erp_with_source(self, country: str = "US"):
        return self._erp, self._source


class _StubBeta:
    def __init__(self, deps=None) -> None:
        self.deps = deps

    async def execute(self, instrument, **params):
        from showme.engine.core.base_function import FunctionResult
        return FunctionResult(
            code="BETA",
            instrument=instrument,
            data={"status": "ok", "betas": {"5Y": {"beta": 1.2}}},
            sources=["yfinance"],
        )


class _BrokenBeta:
    def __init__(self, deps=None) -> None:
        self.deps = deps

    async def execute(self, instrument, **params):
        raise RuntimeError("yfinance offline")


_FULL_RAW = {"marketCap": 300.0, "totalDebt": 100.0, "sector": "Consumer Cyclical"}


def _instrument(symbol: str = "AAPL") -> Instrument:
    return Instrument(symbol=symbol, asset_class=AssetClass.EQUITY)


def _deps(*, raw: dict[str, Any] | None = None, fred: dict[str, float] | None = None,
          damodaran: Any = None) -> FunctionDeps:
    fred_table = {"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93} if fred is None else fred
    return FunctionDeps(
        yfinance=_FakeYf(raw=_FULL_RAW if raw is None else raw),
        fred=_FakeFred(fred_table),
        damodaran=damodaran,
    )


def _run(deps: FunctionDeps, **params: Any):
    return asyncio.run(WACCFunction(deps).execute(_instrument(), **params))


# ---- T10: beta outage must not become a synthetic ok result --------------


def test_t10_beta_outage_is_provider_unavailable_not_synthetic_ok(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _BrokenBeta)
    res = _run(_deps(damodaran=_FakeDamodaran()))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None
    assert res.data["beta"] is None
    assert "synthetic_beta" not in res.sources
    assert res.data["reason"]
    assert res.data["next_actions"]


def test_t10_no_beta_substitute_of_one(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _BrokenBeta)
    res = _run(_deps(damodaran=_FakeDamodaran()))
    assert res.data["beta"] != 1.0
    assert res.data["re_capm"] is None


def test_user_beta_still_computes_wacc(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _BrokenBeta)
    res = _run(_deps(damodaran=_FakeDamodaran()), beta=1.1)
    assert res.data["status"] == "ok"
    assert res.data["beta"] == pytest.approx(1.1)
    assert res.data["wacc"] is not None


def test_missing_risk_free_rate_is_not_replaced_by_four_percent(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)
    res = _run(_deps(fred={"BAMLC0A4CBBBEY": 5.93}, damodaran=_FakeDamodaran()))
    assert res.data["rf"] is None
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None
    assert "fred" not in res.sources


def test_missing_cost_of_debt_is_not_replaced_by_five_point_five(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)
    res = _run(_deps(fred={"DGS10": 4.0}, damodaran=_FakeDamodaran()))
    assert res.data["rd"] is None
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None


def test_missing_capital_structure_is_not_a_70_30_default(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)
    res = _run(_deps(raw={"sector": "Consumer Cyclical"}, damodaran=_FakeDamodaran()))
    assert res.data["equity_weight"] is None
    assert res.data["debt_weight"] is None
    assert res.data["status"] == "provider_unavailable"
    assert res.data["wacc"] is None
