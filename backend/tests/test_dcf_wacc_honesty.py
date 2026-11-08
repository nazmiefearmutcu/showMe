"""DCF must not substitute a constant WACC when the WACC lookup fails.

Residual of DCF#1: dcf.py fell back to wacc=0.08 with status ok whenever the
WACC lookup raised or returned no value. The fallback is now an explicit
needs_input state; a caller-supplied wacc still runs the model. The WACC
function and yfinance are faked; no network is used.
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


def test_failed_wacc_lookup_is_provider_unavailable_not_eight_percent(monkeypatch: pytest.MonkeyPatch) -> None:
    # A failing WACC provider is a provider outage (merged DCF#1 + WACC#1 fix),
    # never a silent 8% discount rate.
    async def boom(self, instrument=None, **params):
        raise RuntimeError("wacc provider down")

    monkeypatch.setattr(WACCFunction, "execute", boom)
    result = _run()
    assert result.data["status"] == "provider_unavailable"
    assert "wacc provider down" in result.data["reason"]
    assert result.data.get("wacc") is None
    assert result.data["fair_value_per_share"] is None
    assert result.data["rows"] == []
    assert any("wacc" in w.lower() for w in result.warnings), result.warnings


def test_wacc_result_without_value_is_needs_input(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty(self, instrument=None, **params):
        return FunctionResult(code="WACC", instrument=instrument, data={"status": "empty"})

    monkeypatch.setattr(WACCFunction, "execute", empty)
    result = _run()
    assert result.data["status"] == "needs_input"
    assert result.data.get("wacc") is None
    assert result.data["rows"] == []


def test_caller_wacc_runs_model_without_lookup(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_run(self, instrument=None, **params):
        raise AssertionError("WACC lookup must not run when the caller sends wacc")

    monkeypatch.setattr(WACCFunction, "execute", must_not_run)
    result = _run(wacc=0.09)
    assert result.data["status"] == "ok"
    assert result.data["wacc"] == 0.09
    assert result.data["fair_value_per_share"] is not None


def test_wacc_source_is_labelled(monkeypatch: pytest.MonkeyPatch) -> None:
    """Review of DCF#1: the output must say where WACC came from."""
    async def model(self, instrument=None, **params):
        return FunctionResult(code="WACC", instrument=instrument,
                              data={"status": "ok", "wacc": 0.087, "re_capm": 0.095},
                              sources=["yfinance", "fred"])

    monkeypatch.setattr(WACCFunction, "execute", model)
    from_model = _run()
    assert from_model.data["status"] == "ok"
    # DCFS#2: FCFE is discounted at the cost of equity; the WACC is reference only.
    assert from_model.data["discount_rate"] == 0.095
    assert from_model.data["wacc"] == 0.087
    assert from_model.data["wacc_source"] == "cost_of_equity"
    assert _run(wacc=0.09).data["wacc_source"] == "input"
