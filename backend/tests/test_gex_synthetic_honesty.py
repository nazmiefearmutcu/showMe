"""GEX data-honesty regressions.

The GEX function used to fall back to a synthetic 3-strike reference
model (hardcoded OI, constant IV) when the live yfinance options chain
was unavailable, and served it with status "ok".

These tests pin the honest contract that replaced it (wc1-g06):

* no modeled grid is ever served; a missing chain is an explicit
  non-ok state with no rows;
* a genuinely live chain is NOT flagged synthetic and keeps a clean
  ``live_chain`` ``source_mode`` with no warning.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from showme.engine.core.base_data_source import DataKind
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.derivative.gex import GEXFunction


def _summary(payload: dict) -> dict:
    return payload.get("summary") or {}


# wc1-g06 (GEX#5): the synthetic 3-strike reference model is gone. Its fixed OI
# and IV were invented numbers served with status "ok". These tests now pin the
# honest replacement: no modeled grid, an explicit non-ok status and no rows.


def test_no_live_options_path_is_honest_not_synthetic() -> None:
    """live_options not requested -> needs_input, no modeled strike grid."""
    fn = GEXFunction(deps=FunctionDeps(yfinance=None))
    result = asyncio.run(fn.execute(symbol="SPY", spot=100.0))
    assert result.data["status"] == "needs_input"
    assert result.data["rows"] == []
    summary = _summary(result.data)
    assert summary.get("synthetic") is False
    assert summary.get("net_gex") is None


class _EmptyChainYf:
    """yfinance stub that connects but returns an empty options chain,
    forcing the live-path synthetic fallback inside ``execute``."""

    async def fetch(self, request):  # noqa: ANN001
        if request.kind == DataKind.OPTIONS_CHAIN:
            if request.extra.get("expiry") is None:
                # expiry-list call
                return {"expiries": ["2026-07-17"]}
            # per-expiry call — empty chain forces the synthetic fallback
            return {"calls": None, "puts": None}
        return None


def test_live_path_empty_chain_is_unavailable_not_synthetic() -> None:
    fn = GEXFunction(deps=FunctionDeps(yfinance=_EmptyChainYf()))
    result = asyncio.run(
        fn.execute(symbol="SPY", spot=100.0, live_options=True)
    )
    # Previously this ran the live code, found no chain and served an invented
    # 3-strike grid with status "ok". It must now be an explicit unavailable state.
    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    summary = _summary(result.data)
    assert summary.get("synthetic") is False
    assert summary.get("source_mode") == "unavailable"
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
        # Stamp the rows with today's trade time so this is a genuinely live
        # chain (wc1-g06 GEX#6: an unstamped chain is not claimed as live).
        now_stamp = pd.Timestamp(datetime.now(timezone.utc))
        df_calls["lastTradeDate"] = now_stamp
        df_puts["lastTradeDate"] = now_stamp
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
