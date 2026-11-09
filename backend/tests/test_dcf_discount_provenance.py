"""DCFS#2 residual: discount-rate labels and provenance on the FCFE DCF path.

- DCFS grid buckets, tornado input and methodology must not call the discount rate
  "WACC": the default rate is the CAPM cost of equity.
- A caller-supplied rate must not be reported under the WACC-model key ``wacc``.
- When the cost of equity rests on a constant ERP (erp_source assumption_default_5pct),
  the DCF payload must carry that provenance and a warning. No network: the WACC
  model and yfinance are faked.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from showme.engine.core.base_function import FunctionDeps, FunctionResult
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DCFFunction
from showme.engine.functions.equity.dcfs import DCFSensitivityFunction
from showme.engine.functions.equity.wacc import WACCFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Yf:
    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": {"freeCashflow": 1.0566e11}}, shares_outstanding=1.4532e10)


def _wacc_model(monkeypatch: pytest.MonkeyPatch, **data) -> None:
    payload = {"status": "ok", "wacc": 0.0994, "re_capm": 0.1057}
    payload.update(data)

    async def model(self, instrument=None, **params):
        return FunctionResult(code="WACC", instrument=instrument, data=payload,
                              sources=["yfinance", "fred"])

    monkeypatch.setattr(WACCFunction, "execute", model)


def test_dcfs_grid_and_methodology_do_not_call_discount_rate_wacc(monkeypatch: pytest.MonkeyPatch) -> None:
    _wacc_model(monkeypatch)
    res = asyncio.run(DCFSensitivityFunction(FunctionDeps(yfinance=_Yf())).execute(
        AAPL, years=5, growth_high=0.05, wacc_range=[0.08, 0.10], g_range=[0.02, 0.025]))
    buckets = [cell["bucket"] for cell in res.data["grid"]]
    assert buckets, res.data
    assert all("WACC" not in b for b in buckets), buckets
    assert all(b.startswith("discount rate") for b in buckets), buckets
    assert "WACC" not in res.data["methodology"]
    assert "discount rate" in res.data["methodology"].lower()
    assert "discount_rate" in res.data["field_dictionary"]["wacc"]


def test_dcfs_tornado_input_is_labelled_discount_rate(monkeypatch: pytest.MonkeyPatch) -> None:
    _wacc_model(monkeypatch)
    res = asyncio.run(DCFSensitivityFunction(FunctionDeps(yfinance=_Yf())).execute(
        AAPL, years=5, growth_high=0.05, wacc_range=[0.08], g_range=[0.025]))
    inputs = {row["input"] for row in res.data["tornado"]}
    assert "discount_rate" in inputs, inputs
    assert "wacc" not in inputs, inputs


def test_caller_rate_is_not_reported_under_wacc_model_key(monkeypatch: pytest.MonkeyPatch) -> None:
    async def must_not_run(self, instrument=None, **params):
        raise AssertionError("WACC model must not run when the caller sends a rate")

    monkeypatch.setattr(WACCFunction, "execute", must_not_run)
    res = asyncio.run(DCFFunction(FunctionDeps(yfinance=_Yf())).execute(
        AAPL, years=5, growth_high=0.05, growth_terminal=0.025, wacc=0.09))
    assert res.data["discount_rate"] == pytest.approx(0.09)
    assert res.data["wacc"] is None
    assert res.data["assumptions"]["wacc"] is None
    assert res.data["wacc_source"] == "input"


def test_constant_erp_provenance_reaches_dcf_payload(monkeypatch: pytest.MonkeyPatch) -> None:
    _wacc_model(monkeypatch, erp_source="assumption_default_5pct", data_state="partial")
    res = asyncio.run(DCFFunction(FunctionDeps(yfinance=_Yf())).execute(
        AAPL, years=5, growth_high=0.05, growth_terminal=0.025))
    assert res.data["erp_source"] == "assumption_default_5pct", res.data
    assert res.data["discount_rate_data_state"] == "partial", res.data
    assert res.data["assumptions"]["erp_source"] == "assumption_default_5pct"
    assert any("5.0%" in w or "5%" in w for w in res.warnings), res.warnings


def test_provider_erp_is_labelled_without_constant_warning(monkeypatch: pytest.MonkeyPatch) -> None:
    _wacc_model(monkeypatch, erp_source="damodaran_cache", data_state="live")
    res = asyncio.run(DCFFunction(FunctionDeps(yfinance=_Yf())).execute(
        AAPL, years=5, growth_high=0.05, growth_terminal=0.025))
    assert res.data["erp_source"] == "damodaran_cache"
    assert res.data["discount_rate_data_state"] == "live"
    assert not any("constant" in w.lower() for w in res.warnings), res.warnings
