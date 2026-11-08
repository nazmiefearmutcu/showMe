"""BMTX#5 regression: the live budget is enforced for CPU-bound backtests.

The backtest loop is synchronous. Before the fix, ``asyncio.wait_for`` could
not interrupt it: the event loop was blocked for the whole run, and a run
longer than LIVE_TIMEOUT_S still came back as status "ok". The compute now runs
in a worker thread, so the budget fires, the caller gets an honest
provider_unavailable state, and the event loop keeps serving other work.
"""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Any

import numpy as np
import pandas as pd
import pytest

import showme.engine.functions.portfolio.bmtx as bmtx_mod
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.bmtx import BMTXFunction


def _ohlcv(days: int = 400, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    periods = pd.date_range(end=datetime.now(timezone.utc).date(), periods=days, freq="B")
    close = np.abs(100 + np.cumsum(rng.normal(0.05, 1.0, len(periods)))) + 10
    return pd.DataFrame({
        "open": close * 0.999, "high": close * 1.01, "low": close * 0.99,
        "close": close, "volume": 1_000_000.0,
    }, index=periods)


class _Yf:
    async def fetch(self, request: Any) -> pd.DataFrame:
        return _ohlcv()


class _SlowBacktest:
    """Stands in for a CPU-bound run: it blocks its thread for 1.5 s."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        pass

    def run(self) -> None:
        time.sleep(1.5)
        raise RuntimeError("the slow run should have been abandoned by the budget")


def test_cpu_bound_run_hits_the_budget_and_does_not_block_the_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(bmtx_mod, "LIVE_TIMEOUT_S", 0.2)
    monkeypatch.setattr(bmtx_mod, "Backtest", _SlowBacktest)
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf()))

    async def _scenario() -> tuple[Any, float, int]:
        ticks = 0

        async def _ticker() -> None:
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        ticker = asyncio.create_task(_ticker())
        t0 = time.monotonic()
        res = await fn.execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True)
        elapsed = time.monotonic() - t0
        ticker.cancel()
        return res, elapsed, ticks

    res, elapsed, ticks = asyncio.run(_scenario())

    assert elapsed < 1.0, f"budget not enforced: returned after {elapsed:.2f}s"
    assert ticks >= 3, "event loop was blocked while the backtest ran"
    assert res.data["status"] == "provider_unavailable"
    assert res.data["cells"] == []
    assert any("timed out" in w for w in res.warnings)
