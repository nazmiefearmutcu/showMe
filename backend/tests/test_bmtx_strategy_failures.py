"""BMTX-R1 regression: a strategy run that raises is reported, not silently dropped.

Before the fix, ``except Exception: continue`` removed a failing cell without a
trace, and the symbol stayed in ``data.symbols`` with no results or reason.
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
    def __init__(self, frames=None) -> None:
        self._frames = dict(frames or {})

    async def fetch(self, request: Any) -> pd.DataFrame:
        return self._frames.get(request.instrument.symbol, _ohlcv())


def test_symbol_whose_every_strategy_fails_is_excluded_with_reason(monkeypatch: pytest.MonkeyPatch) -> None:
    real_backtest = bmtx_mod.Backtest
    bad_frame = _ohlcv(seed=99)

    def fake_backtest(df, fn, **kwargs):
        if df is bad_frame:
            raise ValueError("synthetic engine failure")
        return real_backtest(df, fn, **kwargs)

    monkeypatch.setattr(bmtx_mod, "Backtest", fake_backtest)
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv(), "BADX": bad_frame})))
    res = _run(fn.execute(symbols=["AAPL", "BADX"], strategies=["buy_and_hold"], live_backtest=True))

    assert res.data["status"] == "partial"
    assert res.data["symbols"] == ["AAPL"]
    assert "BADX" in res.data["unavailable_symbols"]
    assert {c["symbol"] for c in res.data["cells"]} == {"AAPL"}
    assert any("BADX" in w and "synthetic engine failure" in w for w in res.warnings)


def _raising_strategy(bars, state):
    raise ValueError("synthetic strategy failure")


def test_partial_strategy_failure_keeps_symbol_and_reports_the_failed_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    # Real engine path: Backtest is NOT patched. The strategy itself raises, and the
    # framework's per-bar catch must not turn that into an ok flat cell (BMTX-R1 follow-up).
    monkeypatch.setitem(STRATEGY_REGISTRY, "rsi_meanrev", _raising_strategy)
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold", "rsi_meanrev"], live_backtest=True))

    assert res.data["status"] == "partial"
    assert res.data["symbols"] == ["AAPL"]
    assert [c["strategy"] for c in res.data["cells"]] == ["buy_and_hold"]
    assert res.data["failed_cells"] == [
        {"symbol": "AAPL", "strategy": "rsi_meanrev", "error": "ValueError: synthetic strategy failure"}
    ]
    assert any("rsi_meanrev" in w and "synthetic strategy failure" in w for w in res.warnings)


def test_raising_strategy_on_real_path_is_never_an_ok_flat_cell(monkeypatch: pytest.MonkeyPatch) -> None:
    # The only strategy raises on every bar. Without the guard the framework holds flat
    # and reports status ok with trades 0; the matrix must instead say it failed.
    monkeypatch.setitem(STRATEGY_REGISTRY, "buy_and_hold", _raising_strategy)
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True))

    # Every cell failed: an empty run with the named cause, never status ok.
    assert res.data["status"] == "empty"
    assert res.data["cells"] == []
    assert res.data["symbols"] == []
    assert "synthetic strategy failure" in res.data["reason"]
    assert any("synthetic strategy failure" in w for w in res.warnings)


def test_all_symbols_failing_every_strategy_is_provider_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_backtest(df, fn, **kwargs):
        raise ValueError("synthetic engine failure")

    monkeypatch.setattr(bmtx_mod, "Backtest", fake_backtest)
    fn = BMTXFunction(FunctionDeps(yfinance=_Yf(frames={"AAPL": _ohlcv()})))
    res = _run(fn.execute(symbols=["AAPL"], strategies=["buy_and_hold"], live_backtest=True))

    # The OHLCV history loaded; the backtest engine raised. That is an empty
    # run with a named cause, not a provider outage.
    assert res.data["status"] == "empty"
    assert res.data["cells"] == []
    assert res.data["symbols"] == []
    assert "synthetic engine failure" in res.data["reason"]
    assert res.metadata["provider_errors"] == []
    assert any("synthetic engine failure" in w for w in res.warnings)
