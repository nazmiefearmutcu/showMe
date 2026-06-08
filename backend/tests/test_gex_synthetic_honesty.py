"""GEX data-honesty regressions.

The GEX function silently falls back to a synthetic 3-strike reference
model (hardcoded OI, constant IV) whenever the live yfinance options
chain is unavailable. Pre-fix it labelled that payload ``source_mode``
``"reference"`` / ``"reference_chain"`` with no machine-readable flag,
so the UI could not tell synthetic data apart from real dealer
positioning.

These tests pin the honest contract:

* the no-live ``_model_gex`` path is flagged ``synthetic`` + carries a
  ``warning`` and an explicit ``source_mode``;
* the live-but-empty-chain fallback inside ``execute`` is *also* flagged
  synthetic (this is the dangerous path — it looks live but isn't);
* a genuinely live chain is NOT flagged synthetic and keeps a clean
  ``live_chain`` ``source_mode`` with no warning.
"""

from __future__ import annotations

import asyncio

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.derivative.gex import GEXFunction, _model_gex


def _summary(payload: dict) -> dict:
    return payload.get("summary") or {}


def test_model_gex_is_flagged_synthetic() -> None:
    payload = _model_gex("SPY", spot=100.0, rate=0.04)
    summary = _summary(payload)
    assert summary.get("synthetic") is True
    assert summary.get("source_mode") == "synthetic_reference"
    # A human-readable warning must accompany the flag so the UI can
    # surface it verbatim.
    assert isinstance(payload.get("warning"), str) and payload["warning"]
    assert "synthetic" in payload["warning"].lower()


def test_no_live_options_path_returns_synthetic() -> None:
    """live_options not requested → synthetic reference model, flagged."""
    fn = GEXFunction(deps=FunctionDeps(yfinance=None))
    result = asyncio.run(fn.execute(symbol="SPY", spot=100.0))
    summary = _summary(result.data)
    assert summary.get("synthetic") is True
    assert summary.get("source_mode") == "synthetic_reference"
    assert "synthetic" in (result.data.get("warning") or "").lower()


class _EmptyChainYf:
    """yfinance stub that connects but returns an empty options chain,
    forcing the live-path synthetic fallback inside ``execute``."""

    async def fetch(self, request):  # noqa: ANN001
        if request.kind == DataKind.OPTIONS_CHAIN:
            return {"expiries": ["2026-07-17"], "calls": None, "puts": None}
        return None


def test_live_path_empty_chain_falls_back_to_flagged_synthetic() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_EmptyChainYf()))
    result = asyncio.run(
        fn.execute(symbol="SPY", spot=100.0, live_options=True)
    )
    summary = _summary(result.data)
    # This is the deceptive path: it ran the live code but had no real
    # chain. It MUST be flagged synthetic, not paraded as live.
    assert summary.get("synthetic") is True
    assert summary.get("source_mode") == "synthetic_reference_chain"
    assert "synthetic" in (result.data.get("warning") or "").lower()
    assert "live_chain" not in summary.get("source_mode", "")


class _LiveChainYf:
    """yfinance stub returning a populated options chain (DataFrame-like)."""

    async def fetch(self, request):  # noqa: ANN001
        if request.kind != DataKind.OPTIONS_CHAIN:
            return None
        import pandas as pd

        if request.extra.get("expiry") is None:
            return {"expiries": ["2026-07-17"]}
        df_calls = pd.DataFrame(
            [
                {"strike": 95.0, "openInterest": 1200, "impliedVolatility": 0.31},
                {"strike": 100.0, "openInterest": 3400, "impliedVolatility": 0.29},
                {"strike": 105.0, "openInterest": 900, "impliedVolatility": 0.33},
            ]
        )
        df_puts = pd.DataFrame(
            [
                {"strike": 95.0, "openInterest": 1500, "impliedVolatility": 0.34},
                {"strike": 100.0, "openInterest": 2800, "impliedVolatility": 0.30},
                {"strike": 105.0, "openInterest": 600, "impliedVolatility": 0.36},
            ]
        )
        return {"calls": df_calls, "puts": df_puts}


def test_live_path_real_chain_is_not_flagged_synthetic() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_LiveChainYf()))
    result = asyncio.run(
        fn.execute(symbol="SPY", spot=100.0, live_options=True)
    )
    summary = _summary(result.data)
    assert summary.get("source_mode") == "live_chain"
    assert not summary.get("synthetic")
    # No degraded warning on the honest path.
    assert not result.data.get("warning")
