"""BMTX#4 regression: an explicit ``live_backtest`` flag beats the injected ``live``.

The agent/pane router injects ``live=True`` for BMTX; the pane's MODEL toggle
sends ``live_backtest=False``. The old ``params.get("live_backtest") or
params.get("live")`` treated False as absent and ran live data under MODEL.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd

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
    """Records every fetch; returns the given frames (or synthetic bars)."""

    def __init__(self, frames=None) -> None:
        self._frames = dict(frames or {})
        self.calls: list[str] = []

    async def fetch(self, request: Any) -> pd.DataFrame:
        sym = request.instrument.symbol
        self.calls.append(sym)
        return self._frames.get(sym, _ohlcv())


def test_explicit_live_backtest_false_wins_over_injected_live() -> None:
    yf = _Yf(frames={"AAPL": _ohlcv()})
    fn = BMTXFunction(FunctionDeps(yfinance=yf))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold"],
                          live_backtest=False, live=True))

    assert res.data["status"] == "needs_input"
    assert yf.calls == []
    assert res.sources == []
    assert all(cell["sharpe"] is None for cell in res.data["cells"])


def test_explicit_live_backtest_true_wins_over_injected_live_false() -> None:
    yf = _Yf(frames={"AAPL": _ohlcv()})
    fn = BMTXFunction(FunctionDeps(yfinance=yf))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold"],
                          live_backtest=True, live=False))

    assert res.data["status"] == "ok"
    assert yf.calls == ["AAPL"]
    assert res.data["cells"][0]["sharpe"] is not None


def test_explicit_live_false_always_carries_a_warning() -> None:
    # BMTX#2 guard: the offline path must never be silent. Already true at HEAD.
    res = _run(BMTXFunction().execute(symbols=["AAPL"], strategies=["sma_crossover"], live_backtest=False))
    assert res.warnings
    assert res.data["status"] == "needs_input"
