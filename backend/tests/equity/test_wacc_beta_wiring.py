"""WACC β-wiring regression — Bug #17.

The 2026-05-24 BugHunt found WACC reporting β=1.0 for AAPL while the
dedicated BETA pane reported β=1.20. The two views ran different code
paths: BETA called yfinance, WACC silently defaulted to 1.0 and emitted
no warning. WACC now:

  - Always invokes ``BetaFunction.execute`` (sharing the same adapter),
    asking for 5Y/2Y/1Y windows and preferring the longest one available.
  - Surfaces ``data_state="synthetic_beta"`` + a warning when the lookup
    failed and we had to fall back to β=1.0.

This file pins both branches.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[3]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.equity import wacc as wacc_mod  # noqa: E402
from showme.engine.functions.equity.wacc import WACCFunction  # noqa: E402


def _aapl() -> Instrument:
    return Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _StubBeta:
    """Drop-in for BetaFunction that returns the BETA-pane β=1.20 value."""

    def __init__(self, deps=None, beta_value: float = 1.20) -> None:
        self.deps = deps
        self._beta_value = beta_value

    async def execute(self, instrument, **params):
        from showme.engine.core.base_function import FunctionResult
        return FunctionResult(
            code="BETA",
            instrument=instrument,
            data={
                "status": "ok",
                "benchmark": "SPY",
                "betas": {
                    "5Y": {"beta": self._beta_value, "correlation": 0.62,
                            "samples": 1260, "annualized_volatility_target": 0.27,
                            "annualized_volatility_bench": 0.18},
                    "2Y": {"beta": self._beta_value - 0.05, "correlation": 0.59,
                            "samples": 504, "annualized_volatility_target": 0.26,
                            "annualized_volatility_bench": 0.17},
                    "1Y": {"beta": self._beta_value - 0.10, "correlation": 0.61,
                            "samples": 252, "annualized_volatility_target": 0.25,
                            "annualized_volatility_bench": 0.17},
                },
            },
            sources=["yfinance"],
        )


def test_wacc_uses_real_beta_above_1_10_not_hardcoded_one(monkeypatch) -> None:
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)
    result = asyncio.run(WACCFunction().execute(_aapl()))
    payload = result.data
    assert payload["beta"] > 1.10, (
        f"WACC must use the live BETA value (≈1.20) for AAPL, "
        f"not the hardcoded 1.0 fallback; got {payload['beta']}"
    )
    assert payload["beta_source"] == "beta_5y"
    assert payload["beta_window"] == "5Y"
    assert payload["data_state"] == "live"
    assert "beta" in result.sources
    assert not any("synthetic" in w.lower() for w in result.warnings)


def test_wacc_prefers_5y_window_over_shorter_windows(monkeypatch) -> None:
    class _StubBetaPartial:
        def __init__(self, deps=None) -> None:
            self.deps = deps

        async def execute(self, instrument, **params):
            from showme.engine.core.base_function import FunctionResult
            return FunctionResult(
                code="BETA",
                instrument=instrument,
                data={
                    "betas": {
                        "5Y": {"beta": 1.42},
                        "2Y": {"beta": 0.85},
                        "1Y": {"beta": 0.50},
                    },
                },
                sources=["yfinance"],
            )

    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaPartial)
    result = asyncio.run(WACCFunction().execute(_aapl()))
    assert result.data["beta"] == pytest.approx(1.42)
    assert result.data["beta_window"] == "5Y"


def test_wacc_falls_through_2y_when_5y_missing(monkeypatch) -> None:
    class _StubBetaNo5Y:
        def __init__(self, deps=None) -> None:
            self.deps = deps

        async def execute(self, instrument, **params):
            from showme.engine.core.base_function import FunctionResult
            return FunctionResult(
                code="BETA",
                instrument=instrument,
                data={"betas": {"2Y": {"beta": 1.15}, "1Y": {"beta": 1.05}}},
                sources=["yfinance"],
            )

    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaNo5Y)
    result = asyncio.run(WACCFunction().execute(_aapl()))
    assert result.data["beta"] == pytest.approx(1.15)
    assert result.data["beta_window"] == "2Y"


def test_wacc_labels_synthetic_when_beta_lookup_fails(monkeypatch) -> None:
    class _StubBetaBroken:
        def __init__(self, deps=None) -> None:
            self.deps = deps

        async def execute(self, instrument, **params):
            raise RuntimeError("yfinance offline")

    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaBroken)
    result = asyncio.run(WACCFunction().execute(_aapl()))
    assert result.data["beta"] == 1.0
    assert result.data["data_state"] == "synthetic_beta"
    assert result.data["beta_source"] == "synthetic_beta"
    assert any("synthetic" in w.lower() for w in result.warnings)
    assert "synthetic_beta" in result.sources


def test_wacc_labels_synthetic_when_beta_returns_empty_payload(monkeypatch) -> None:
    class _StubBetaEmpty:
        def __init__(self, deps=None) -> None:
            self.deps = deps

        async def execute(self, instrument, **params):
            from showme.engine.core.base_function import FunctionResult
            return FunctionResult(
                code="BETA",
                instrument=instrument,
                data={"status": "provider_unavailable", "betas": {}},
                sources=["no_live_source"],
            )

    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBetaEmpty)
    result = asyncio.run(WACCFunction().execute(_aapl()))
    assert result.data["beta"] == 1.0
    assert result.data["data_state"] == "synthetic_beta"
    assert any("synthetic" in w.lower() for w in result.warnings)


def test_wacc_user_supplied_beta_overrides_lookup(monkeypatch) -> None:
    """Belt-and-suspenders: explicit ?beta=0.7 must still win."""
    monkeypatch.setattr(wacc_mod, "BetaFunction", _StubBeta)
    result = asyncio.run(WACCFunction().execute(_aapl(), beta=0.7))
    assert result.data["beta"] == pytest.approx(0.7)
    assert result.data["beta_source"] == "user_input"
    assert "user_input" in result.sources
