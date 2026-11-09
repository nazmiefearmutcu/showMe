"""DDM sensitivity surface must be a true Gordon grid (DDM#2).

Each surface cell is D1 / (r - g) with D1 = D0 * (1 + g) recomputed for the
cell's own growth column. Holding the base-case D1 fixed across growth columns
understates the growth sensitivity. The provider is faked; no network is used.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DDMFunction

MSFT = Instrument(symbol="MSFT", asset_class=AssetClass.EQUITY)


class _Yf:
    def __init__(self, raw: dict) -> None:
        self._raw = raw

    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": self._raw}, shares_outstanding=None)


def _run(**params):
    deps = FunctionDeps(yfinance=_Yf({"trailingAnnualDividendRate": 3.71, "dividendRate": 3.92}))
    return asyncio.run(DDMFunction(deps).execute(MSFT, **params))


def test_surface_cells_recompute_d1_for_each_growth_column() -> None:
    res = _run(required_return=0.09, growth_rate=0.03)
    assert res.data["status"] == "ok"
    d0 = res.data["dividend_ttm"]
    cells = {(c["required_return"], c["growth"]): c["value"] for c in res.data["surface"]}
    for (req, grow), value in cells.items():
        if req <= grow:
            assert value is None
            continue
        expected = d0 * (1 + grow) / (req - grow)
        # Red before the fix: the g-column cells reuse the base-case D1.
        assert value == pytest.approx(expected, rel=1e-9), (req, grow, value, expected)


class _YfRaw:
    def __init__(self, raw: dict) -> None:
        self._raw = raw

    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": self._raw}, shares_outstanding=None)


def test_d0_is_trailing_dividend_not_forward_indicated_rate() -> None:
    """DDM#1: dividendRate is the forward indicated annual rate (not yet paid).

    D0 must be the trailing dividend (trailingAnnualDividendRate). Growing a
    forward rate by (1+g) again double-counts one year of growth.
    """
    deps = FunctionDeps(yfinance=_YfRaw({"dividendRate": 3.92, "trailingAnnualDividendRate": 3.71}))
    res = asyncio.run(DDMFunction(deps).execute(MSFT, required_return=0.09, growth_rate=0.03))
    assert res.data["status"] == "ok"
    # Red before the fix: dividend_ttm was 3.92 (the forward rate).
    assert res.data["dividend_ttm"] == 3.71
    assert res.data["next_dividend"] == 3.71 * 1.03
    assert res.data["rows"][0]["value"] == 3.71
    assert res.data["fair_value_per_share"] == 3.71 * 1.03 / (0.09 - 0.03)


def test_offline_provider_without_data_is_explicit_state_not_live_ok() -> None:
    """T10: with the provider unreachable, DDM must not return ok/live.

    yfinance's REFDATA adapter swallows an info failure and returns raw with
    only ``info_error``. DDM must report provider_unavailable with no value
    (never ok with a zero dividend). The router must also not inject a
    constant required_return (see test_ddm_router_injects_no_constant_return).
    """
    deps = FunctionDeps(yfinance=_YfRaw({"info_error": "connection refused"}))
    res = asyncio.run(DDMFunction(deps).execute(MSFT))
    assert res.data["status"] == "provider_unavailable"
    assert res.data["fair_value_per_share"] is None
    assert res.data["required_return"] is None
    assert res.data["reason"]
    assert res.data["next_actions"]


def test_ddm_router_injects_no_constant_return() -> None:
    """T10 root cause: the router injected required_return=0.08, so DDM never
    reached the WACC model and valued at a silent constant (WACC policy)."""
    from showme.server_routes._agent_runtime import _route_function_params

    routed = _route_function_params("DDM", {"symbol": "AAPL"})
    assert "required_return" not in routed


def test_ddm_non_payer_is_not_applicable_not_ok() -> None:
    deps = FunctionDeps(yfinance=_YfRaw({"sector": "Technology", "marketCap": 1.0}))
    res = asyncio.run(DDMFunction(deps).execute(MSFT, required_return=0.09, growth_rate=0.03))
    assert res.data["status"] == "not_applicable"
    assert res.data["fair_value_per_share"] is None
