"""DCFS#2: FCFE is discounted at the cost of equity, not the enterprise WACC.

yfinance freeCashflow is levered free cash flow to equity (after debt). Discounting
it at WACC (which blends in the after-tax cost of debt) mixes the claims. The default
discount rate is now the CAPM cost of equity (re_capm) from the WACC model. A caller
supplied wacc still applies as an explicit override, labelled as such. No network:
the WACC model and yfinance are faked.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DCFFunction
from showme.engine.functions.equity.wacc import WACCFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Yf:
    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": {"freeCashflow": 1.0566e11}}, shares_outstanding=1.4532e10)


def _run(**params):
    base = {"growth_high": 0.05, "growth_terminal": 0.025, "years": 5}
    base.update(params)
    return asyncio.run(DCFFunction(FunctionDeps(yfinance=_Yf())).execute(AAPL, **base))


def _wacc_model(monkeypatch: pytest.MonkeyPatch, *, wacc: float | None, re_capm: float | None,
                status: str = "ok") -> None:
    async def model(self, instrument=None, **params):
        return FunctionResult(code="WACC", instrument=instrument,
                              data={"status": status, "wacc": wacc, "re_capm": re_capm},
                              sources=["yfinance", "fred"])

    monkeypatch.setattr(WACCFunction, "execute", model)


def test_default_discount_rate_is_cost_of_equity(monkeypatch: pytest.MonkeyPatch) -> None:
    _wacc_model(monkeypatch, wacc=0.099407, re_capm=0.105710)
    res = _run()
    assert res.data["status"] == "ok"
    assert res.data["discount_rate"] == pytest.approx(0.105710)
    assert res.data["cost_of_equity"] == pytest.approx(0.105710)
    assert res.data["wacc_source"] == "cost_of_equity"
    # The WACC model value is reported for reference, not used to discount.
    assert res.data["wacc"] == pytest.approx(0.099407)


def test_default_valuation_equals_explicit_cost_of_equity_run(monkeypatch: pytest.MonkeyPatch) -> None:
    _wacc_model(monkeypatch, wacc=0.099407, re_capm=0.105710)
    default = _run()
    explicit = _run(wacc=0.105710)
    assert default.data["equity_value"] == pytest.approx(explicit.data["equity_value"])
    assert default.data["equity_value"] != pytest.approx(_run(wacc=0.099407).data["equity_value"])


def test_missing_cost_of_equity_is_not_replaced_by_wacc(monkeypatch: pytest.MonkeyPatch) -> None:
    _wacc_model(monkeypatch, wacc=0.099407, re_capm=None, status="provider_unavailable")
    res = _run()
    assert res.data["status"] == "provider_unavailable"
    assert res.data["discount_rate"] is None
    assert res.data["fair_value_per_share"] is None
    assert res.data["rows"] == []


def test_caller_supplied_rate_is_applied_and_labelled(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_run(self, instrument=None, **params):
        raise AssertionError("WACC model must not run when the caller sends a rate")

    monkeypatch.setattr(WACCFunction, "execute", must_not_run)
    res = _run(wacc=0.09)
    assert res.data["discount_rate"] == 0.09
    assert res.data["wacc_source"] == "input"
    assert any("cost of equity" in w.lower() for w in res.warnings), res.warnings
