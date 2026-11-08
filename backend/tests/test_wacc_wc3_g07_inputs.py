"""WACC#5 (wc3-g07): the manifest declares every assumption the WACC pane sends.

The pane exposes ERP, beta window, beta, rf, Rd and the tax rate. Each one must
be a declared seed input (so the help text and the generic form advertise it)
and the handler must read it under the same name. No network: the tests only
read the registry and run the handler with faked providers.
"""
from __future__ import annotations

import asyncio
from typing import Any

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity import wacc as wacc_mod
from showme.engine.functions.equity.wacc import WACCFunction
from showme.manifest import REGISTRY, ControlKind, load_seeds

PANE_SENT_INPUTS = ("market_premium", "beta_window", "beta", "rf", "rd", "tax_rate_override")


def _wacc_manifest():
    load_seeds()
    return REGISTRY.get("WACC")


def test_seed_declares_every_input_the_pane_sends() -> None:
    names = {spec.name for spec in _wacc_manifest().inputs}
    missing = [name for name in PANE_SENT_INPUTS if name not in names]
    assert not missing, f"WACC seed must declare the pane inputs, missing {missing}"


def test_seed_assumption_inputs_are_model_assumptions_with_units() -> None:
    specs = {spec.name: spec for spec in _wacc_manifest().inputs}
    for name in ("market_premium", "rf", "rd", "tax_rate_override"):
        assert specs[name].control == ControlKind.MODEL_ASSUMPTION, name
        assert specs[name].unit == "decimal", name
        assert specs[name].required is False, name
    assert specs["beta"].control == ControlKind.MODEL_ASSUMPTION
    assert specs["beta"].required is False
    assert specs["beta_window"].options == ["252d", "504d"]


class _Refdata:
    country = "US"
    market_cap = None
    extras = {"raw": {"marketCap": 300.0, "totalDebt": 100.0, "sector": "Consumer Cyclical",
                      "interestExpense": 5.0}}


class _Yf:
    async def fetch(self, request):
        from showme.engine.core.base_data_source import DataKind
        if request.kind == DataKind.REFDATA:
            return _Refdata()
        if request.kind == DataKind.FUNDAMENTALS:
            raise RuntimeError("no statements")
        raise NotImplementedError


class _Fred:
    api_key = "test-key"

    async def series(self, sid: str, frequency: str = "d"):
        values = {"DGS10": 4.0, "BAMLC0A4CBBBEY": 5.93}
        if sid not in values:
            return pd.DataFrame()
        return pd.DataFrame({"value": [values[sid]]})


class _Damo:
    async def get_erp_with_source(self, country: str = "US"):
        return 0.046, "damodaran_cache"


class _NoBeta:
    def __init__(self, deps=None) -> None:
        self.deps = deps

    async def execute(self, instrument, **params: Any):
        raise AssertionError("BetaFunction must not run when the caller sets beta")


def _run(**params: Any):
    deps = FunctionDeps(yfinance=_Yf(), fred=_Fred(), damodaran=_Damo())
    inst = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)
    return asyncio.run(WACCFunction(deps).execute(inst, **params))


def test_handler_reads_pane_beta_rf_and_rd_overrides(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _NoBeta)
    res = _run(beta=1.2, rf=0.04, rd=0.05)
    assert res.data["beta"] == 1.2
    assert res.data["beta_source"] == "user_input"
    assert res.data["rf"] == 0.04
    assert res.data["rd"] == 0.05
    assert res.data["rd_source"] == "user_input"
    assert res.data["input_quality"]["rf"] == "user"
    assert res.data["input_quality"]["rd"] == "user"
