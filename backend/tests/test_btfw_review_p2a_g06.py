"""P2A-G06 review fix for BTFW#4 (no synthetic history in live mode).

live=true without OHLCV used to run the walk-forward on a synthetic sine
ramp and return status 'ok'. The DATA POLICY forbids that substitution: the
run must report an explicit provider_unavailable state with no metrics.
All tests are offline: the OHLCV fetcher is stubbed.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio.btfw import BTFWFunction


def _inst() -> Instrument:
    return Instrument(symbol="TEST", asset_class=AssetClass.EQUITY)


class _EmptyYF:
    async def fetch(self, req):
        return pd.DataFrame()


class _RaisingYF:
    async def fetch(self, req):
        raise RuntimeError("upstream down")


def _assert_unavailable(result) -> None:
    d = result.data
    assert d["status"] == "provider_unavailable"
    assert d["measured"] is False
    assert d["equity_curve"] == []
    assert d["oos_equity_curve"] == []
    assert d["final_equity"] is None
    assert d["summary"]["oos_sharpe"] is None
    assert d["reason"]
    assert "local_backtest_model" not in result.sources
    assert result.metadata.get("synthetic_history") is not True


def test_btfw4_live_without_provider_is_unavailable_not_synthetic() -> None:
    """Was: the sine-ramp history was walked forward and reported as status ok."""
    res = asyncio.run(BTFWFunction(FunctionDeps(yfinance=None)).execute(
        instrument=_inst(), live=True, strategy="sma_crossover"))
    _assert_unavailable(res)


def test_btfw4_live_with_empty_ohlcv_is_unavailable() -> None:
    res = asyncio.run(BTFWFunction(FunctionDeps(yfinance=_EmptyYF())).execute(
        instrument=_inst(), live=True, strategy="sma_crossover"))
    _assert_unavailable(res)


def test_btfw4_live_with_fetch_error_is_unavailable_and_names_the_error() -> None:
    res = asyncio.run(BTFWFunction(FunctionDeps(yfinance=_RaisingYF())).execute(
        instrument=_inst(), live=True, strategy="sma_crossover"))
    _assert_unavailable(res)
    assert "RuntimeError" in res.data["reason"]
