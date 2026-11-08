"""BMTX#5 regression: the seed-declared cost inputs are read, not ignored.

The seed declares initial_equity (100000), commission_bps (5) and slippage_bps
(2). The handler previously hard-coded initial_cash=10,000, used only fee_bps
and never applied slippage.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.bmtx import BMTXFunction


def _run(coro):
    return asyncio.run(coro)


def _ohlcv(days: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    periods = pd.date_range(end=datetime.now(timezone.utc).date(), periods=days, freq="B")
    close = 100 + np.cumsum(rng.normal(0.05, 1.0, len(periods)))
    close = np.abs(close) + 10
    return pd.DataFrame({
        "open": close * 0.999,
        "high": close * 1.01,
        "low": close * 0.99,
        "close": close,
        "volume": 1_000_000.0,
    }, index=periods)


class _Yf:
    def __init__(self, frames=None) -> None:
        self._frames = dict(frames or {})

    async def fetch(self, request: Any) -> pd.DataFrame:
        return self._frames.get(request.instrument.symbol, _ohlcv())


def _fn() -> BMTXFunction:
    return BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))


def test_initial_equity_default_matches_seed_and_scales_final_equity() -> None:
    default = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True))
    custom = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True,
                                initial_equity=50_000))

    d = default.data["cells"][0]
    c = custom.data["cells"][0]
    assert d["final_equity"] == pytest.approx(100_000 * (1 + d["total_return"]), rel=1e-9)
    assert c["final_equity"] == pytest.approx(50_000 * (1 + c["total_return"]), rel=1e-9)
    # Returns are ratios, so the starting equity must not change them.
    assert c["total_return"] == pytest.approx(d["total_return"], rel=1e-9)


def test_slippage_input_reduces_return() -> None:
    base = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True,
                              commission_bps=0, slippage_bps=0))
    slipped = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True,
                                 commission_bps=0, slippage_bps=100))

    assert slipped.data["cells"][0]["total_return"] < base.data["cells"][0]["total_return"]


def test_commission_input_is_applied() -> None:
    base = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True,
                              commission_bps=0, slippage_bps=0))
    costly = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True,
                                commission_bps=200, slippage_bps=0))

    assert costly.data["cells"][0]["total_return"] < base.data["cells"][0]["total_return"]


def test_costs_are_disclosed_in_methodology() -> None:
    res = _run(_fn().execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True))

    text = res.data["methodology"]
    assert "100,000" in text
    assert "commission 5 bps" in text
    assert "slippage 2 bps" in text
