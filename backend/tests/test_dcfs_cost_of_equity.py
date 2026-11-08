"""DCFS#2: the sensitivity run perturbs the discount rate FCFE is actually discounted at.

The DCF now discounts FCFE at the cost of equity. DCFS must echo that rate and
perturb it in the tornado, not the WACC reference value. No network: the WACC model
and yfinance are faked.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcfs import DCFSensitivityFunction
from showme.engine.functions.equity.wacc import WACCFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Yf:
    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": {"freeCashflow": 1.0566e11}}, shares_outstanding=1.4532e10)


def test_dcfs_base_and_tornado_use_cost_of_equity(monkeypatch: pytest.MonkeyPatch) -> None:
    async def model(self, instrument=None, **params):
        return FunctionResult(code="WACC", instrument=instrument,
                              data={"status": "ok", "wacc": 0.0994, "re_capm": 0.1057},
                              sources=["yfinance", "fred"])

    monkeypatch.setattr(WACCFunction, "execute", model)
    res = asyncio.run(DCFSensitivityFunction(FunctionDeps(yfinance=_Yf())).execute(
        AAPL, years=5, growth_high=0.05, wacc_range=[0.08, 0.10], g_range=[0.02, 0.025]))

    assumptions = res.data["assumptions"]
    assert assumptions["wacc"] == pytest.approx(0.1057), assumptions
    assert assumptions["wacc_reference"] == pytest.approx(0.0994), assumptions

    tornado = {row["input"]: row for row in res.data.get("tornado", [])}
    assert "discount_rate" in tornado, res.data.get("tornado")
    assert tornado["discount_rate"]["low_value"] == pytest.approx(0.1057 * 0.8, rel=1e-3), tornado["discount_rate"]
    assert tornado["discount_rate"]["high_value"] == pytest.approx(0.1057 * 1.2, rel=1e-3), tornado["discount_rate"]
