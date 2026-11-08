"""BMTX#6 regression: the matrix reports an out-of-sample holdout next to the
in-sample ranking, and labels the ranking as in-sample.

Before the fix the cells carried only in-sample metrics, and nothing told the
reader that the top-10 list was ranked on the same bars it was scored on.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio import bmtx as bmtx_mod
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


def test_cells_carry_out_of_sample_holdout_metrics() -> None:
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["sma_crossover"], live_backtest=True))

    cell = res.data["cells"][0]
    assert cell["oos_sharpe"] is not None
    assert cell["oos_total_return"] is not None
    assert cell["oos_max_drawdown"] is not None
    assert res.data["rank_basis"] == "in_sample_sharpe"
    window = res.data["oos_windows"]["AAPL"]
    assert window["test_bars"] > 0
    assert window["train_bars"] > 0
    assert window["test_start"] > window["train_end"]
    assert window["test_end"] >= window["test_start"]


def test_oos_holdout_metrics_come_from_test_slice_only() -> None:
    frames = {"AAPL": _ohlcv()}
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames=frames)))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True))

    cell = res.data["cells"][0]
    window = res.data["oos_windows"]["AAPL"]
    close = frames["AAPL"]["close"].to_numpy()
    n = len(close)
    test_start = n - window["test_bars"]
    # Buy-and-hold enters at the first scored bar of the holdout (test_start+1)
    # and pays the total cost (commission 5 bps + slippage 2 bps by default).
    fee = (5.0 + 2.0) / 10_000
    expected = (1 - fee) * close[-1] / close[test_start + 1] - 1
    assert cell["oos_total_return"] == pytest.approx(expected, abs=1e-6)


def test_holdout_is_the_final_fraction_of_bars() -> None:
    frames = {"AAPL": _ohlcv(days=400)}
    n = len(frames["AAPL"])
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames=frames)))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["sma_crossover"], live_backtest=True))

    window = res.data["oos_windows"]["AAPL"]
    assert window["train_bars"] + window["test_bars"] == n
    assert window["test_bars"] == int(n * bmtx_mod.OOS_TEST_FRACTION)


def test_ranking_note_says_in_sample_and_methodology_discloses_holdout() -> None:
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["sma_crossover"], live_backtest=True))

    assert "IN-SAMPLE" in res.data["methodology"]
    assert "oos_" in res.data["methodology"]
    assert res.data["field_dictionary"]["rank_basis"].lower().startswith("column")
