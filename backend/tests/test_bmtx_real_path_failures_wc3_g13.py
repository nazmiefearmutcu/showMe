"""BMTX-R1 follow-up: a raising strategy must fail its cell on the REAL engine path.

``Backtest.run`` catches every exception a strategy raises, bar by bar, and holds
the position. Before the fix, BMTX never saw the exception, so a broken strategy
produced an "ok" cell with 0 trades and Sharpe 0.0. These tests do not patch
``Backtest``; the strategy itself raises through the real framework.
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


def _always_raises(bars: pd.DataFrame, state: dict[str, Any]) -> int:
    raise ValueError("strategy boom")


def _raises_late(bars: pd.DataFrame, state: dict[str, Any]) -> int:
    # Raises only once the history is long enough to be traded, so earlier bars look fine.
    if len(bars) > 200:
        raise ValueError("late boom")
    return 0


def test_raising_strategy_is_a_failed_cell_not_an_ok_flat_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(bmtx_mod.STRATEGY_REGISTRY, "always_raises", _always_raises)
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold", "always_raises"], live_backtest=True))

    # Red before the fix: the raising strategy produced an ok cell with 0 trades and sharpe 0.0.
    assert [c["strategy"] for c in res.data["cells"]] == ["buy_and_hold"]
    assert res.data["failed_cells"] == [
        {"symbol": "AAPL", "strategy": "always_raises", "error": "ValueError: strategy boom"}
    ]
    assert res.data["status"] == "partial"
    assert any("always_raises" in w and "strategy boom" in w for w in res.warnings)


def test_strategy_that_raises_only_later_still_fails_its_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(bmtx_mod.STRATEGY_REGISTRY, "raises_late", _raises_late)
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold", "raises_late"], live_backtest=True))

    assert "raises_late" not in [c["strategy"] for c in res.data["cells"]]
    assert any(c["strategy"] == "raises_late" and "late boom" in c["error"]
               for c in res.data["failed_cells"])


def test_all_strategies_raising_on_the_real_path_is_empty_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setitem(bmtx_mod.STRATEGY_REGISTRY, "always_raises", _always_raises)
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["always_raises"], live_backtest=True))

    assert res.data["status"] == "empty"
    assert res.data["cells"] == []
    assert "strategy boom" in res.data["reason"]
    assert res.metadata["provider_errors"] == []


def test_healthy_strategy_on_the_real_path_is_unaffected(monkeypatch: pytest.MonkeyPatch) -> None:
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True))

    assert res.data["status"] == "ok"
    assert [c["strategy"] for c in res.data["cells"]] == ["buy_and_hold"]
    assert res.data["failed_cells"] == []
