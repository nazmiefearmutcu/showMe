"""Every DCF manifest input must reach the model (DCF#2).

The manifest used to declare discount_rate / growth_rate / terminal_growth /
projection_years, while the handler reads wacc / growth_high / growth_terminal
/ years, so the declared names were silently ignored. Each declared input must
change the model output. The provider is faked; no network is used.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DCFFunction
from showme.manifest import REGISTRY, load_seeds

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Yf:
    async def fetch(self, request):
        return SimpleNamespace(
            extras={"raw": {"freeCashflow": 1.0e10}}, shares_outstanding=1.0e9
        )


def _run(**params):
    return asyncio.run(DCFFunction(FunctionDeps(yfinance=_Yf())).execute(AAPL, **params))


def test_declared_dcf_inputs_are_the_names_the_handler_reads() -> None:
    load_seeds()
    declared = {spec.name for spec in REGISTRY.get("DCF").inputs}
    # Red before the fix: discount_rate / growth_rate / terminal_growth /
    # projection_years were declared but never read.
    assert declared == {"symbol", "wacc", "growth_high", "growth_terminal", "years"}


def test_wacc_input_reaches_the_discount_rate() -> None:
    res = _run(wacc=0.12, growth_high=0.05, growth_terminal=0.02, years=5)
    assert res.data["wacc"] == 0.12


def test_years_input_sets_the_projection_length() -> None:
    res = _run(wacc=0.09, growth_high=0.05, growth_terminal=0.02, years=3)
    assert len(res.data["rows"]) == 3


def test_growth_high_input_drives_stage_one_growth() -> None:
    res = _run(wacc=0.09, growth_high=0.2, growth_terminal=0.02, years=3)
    assert res.data["g_high"] == 0.2
    assert res.data["rows"][0]["fcfe"] == 1.0e10 * 1.2


def test_growth_terminal_input_drives_terminal_growth() -> None:
    res = _run(wacc=0.09, growth_high=0.05, growth_terminal=0.01, years=3)
    assert res.data["g_terminal"] == 0.01


def test_handler_defaults_are_the_manifest_defaults() -> None:
    """DCF#4: one set of defaults. The handler must run with the manifest's
    declared defaults when the caller omits them (the pane and API agree)."""
    manifest_defaults = REGISTRY.get("DCF").defaults
    res = _run(wacc=0.09)
    assert res.data["g_high"] == manifest_defaults["growth_high"]
    assert res.data["g_terminal"] == manifest_defaults["growth_terminal"]
    assert res.data["years"] == manifest_defaults["years"]
