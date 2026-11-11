"""BMTX#3 regression: live backtests never fabricate history for symbols.

Before the fix, when every OHLCV fetch failed the handler replaced the data
with a sine-wave template keyed to the first three requested symbols and still
returned status "ok" with Sharpe values for tickers that do not exist.
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
from showme.engine.services.backtest_framework import STRATEGY_REGISTRY


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
    """Fails for symbols in ``fail``; returns real-looking bars for the rest."""

    def __init__(self, fail=(), frames=None) -> None:
        self._fail = set(fail)
        self._frames = dict(frames or {})

    async def fetch(self, request: Any) -> pd.DataFrame:
        sym = request.instrument.symbol
        if sym in self._fail:
            raise RuntimeError(f"no such ticker {sym}")
        return self._frames.get(sym, _ohlcv())


def test_live_all_symbols_unavailable_is_honest_not_template(monkeypatch: pytest.MonkeyPatch) -> None:
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(fail={"ZZQXNOTREAL", "QQQQ9X"})))
    res = _run(fn.execute(symbols=["ZZQXNOTREAL", "QQQQ9X"], live_backtest=True))

    # No matrix is served for tickers that produced no history.
    assert res.data["status"] == "provider_unavailable"
    assert res.data["cells"] == []
    assert res.data["surface"] == []
    assert res.data["symbols"] == []
    assert res.data["summary"]["best_sharpe"] is None
    assert res.data["unavailable_symbols"] == ["ZZQXNOTREAL", "QQQQ9X"]
    assert res.data["next_actions"]
    assert all("local_backtest_model" not in src for src in res.sources)
    assert any("ZZQXNOTREAL" in w for w in res.warnings)


def test_live_partial_failure_excludes_unavailable_symbol_and_warns() -> None:
    strategy = next(iter(STRATEGY_REGISTRY))
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(fail={"BOGUSXYZ"}, frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL", "BOGUSXYZ"], strategies=[strategy], live_backtest=True))

    assert res.data["status"] == "partial"
    assert res.data["symbols"] == ["AAPL"]
    assert {c["symbol"] for c in res.data["cells"]} == {"AAPL"}
    assert res.data["unavailable_symbols"] == ["BOGUSXYZ"]
    assert any("BOGUSXYZ" in w for w in res.warnings)


def test_live_timeout_returns_honest_state_not_reference_template(monkeypatch: pytest.MonkeyPatch) -> None:
    class _Slow(_Yf):
        async def fetch(self, request: Any) -> pd.DataFrame:
            await asyncio.sleep(1.0)
            return _ohlcv()

    monkeypatch.setattr(bmtx_mod, "LIVE_TIMEOUT_S", 0.05, raising=False)
    fn = BMTXFunction(FunctionDeps(yfinance=_Slow()))
    res = _run(fn.execute(symbols=["AAPL"], live_backtest=True))

    assert res.data["status"] == "provider_unavailable"
    assert res.data["cells"] == []
    assert res.data["symbols"] == []
    assert any("timed out" in w for w in res.warnings)
