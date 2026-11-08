"""DCF must source FCFE and shares from the provider when the caller sends none,
label a caller override as such, and never emit zero-valued placeholder rows.

Regression for DCF#1: the pane always sent fcfe=$10,000M and shares=15,000M, so
the provider fallbacks never ran and a placeholder base was shown as fair value.
The yfinance adapter is faked; no network is used.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DCFFunction

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Yf:
    def __init__(self, raw: dict, shares: float | None) -> None:
        self._raw = raw
        self._shares = shares

    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": self._raw}, shares_outstanding=self._shares)


def _run(deps: FunctionDeps, **params):
    base = {"wacc": 0.09, "growth_high": 0.05, "growth_terminal": 0.025, "years": 5}
    base.update(params)
    return asyncio.run(DCFFunction(deps).execute(AAPL, **base))


def test_provider_fcfe_and_shares_are_used_and_labelled() -> None:
    deps = FunctionDeps(yfinance=_Yf({"freeCashflow": 1.0566e11}, 1.4532e10))
    result = _run(deps)
    assert result.data["starting_fcfe"] == 1.0566e11
    assert result.data["fair_value_per_share"] is not None
    assert result.data["fcfe_source"] == "yfinance"
    assert result.data["shares_source"] == "yfinance"


def test_caller_override_is_labelled_as_manual_override() -> None:
    deps = FunctionDeps(yfinance=_Yf({"freeCashflow": 1.0566e11}, 1.4532e10))
    result = _run(deps, fcfe=1.0e10, shares_outstanding=1.5e10)
    assert result.data["starting_fcfe"] == 1.0e10
    assert result.data["fcfe_source"] == "user_override"
    assert result.data["shares_source"] == "user_override"
    assert any("override" in w.lower() for w in result.warnings), result.warnings


def test_missing_provider_fcfe_returns_needs_input_without_zero_rows() -> None:
    deps = FunctionDeps(yfinance=_Yf({}, 1.4532e10))
    result = _run(deps)
    assert result.data["status"] == "needs_input"
    assert result.data["fair_value_per_share"] is None
    # No placeholder cash-flow rows priced at zero.
    assert result.data["rows"] == []
    assert result.data["fcfe_source"] == "missing"
    assert result.data.get("reason")
