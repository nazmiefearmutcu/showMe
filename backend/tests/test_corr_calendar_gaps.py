"""CORR#1 regression: weekend and holiday calendar gaps are not data gaps.

Before the fix, the return frame joined 24/7 crypto with weekday-only equity
and FX series. Weekend rows are NaN for the weekday series, which exceeded the
30% NAN_DROP_THRESHOLD, so the default LIVE universe collapsed to BTCUSDT and
the matrix was empty even though the data existed.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.corr import CORRFunction

END = "2026-09-18"  # a Friday


def _run(coro):
    return asyncio.run(coro)


class _CalendarYf:
    """Weekday-only series for equities/FX, every-day series for crypto."""

    _FREQ = {"AAPL": "B", "EURUSD": "B", "BTCUSDT": "D", "BTC-USD": "D"}

    async def fetch(self, request: Any) -> pd.DataFrame:
        sym = request.instrument.symbol
        freq = self._FREQ.get(sym, "B")
        periods = 160  # ~32 weeks of weekdays, ~5 months of days
        idx = pd.date_range(end=END, periods=periods, freq=freq)
        # Seeded per symbol so the series are stable across runs.
        seed = sum(ord(ch) for ch in sym)
        rng = np.random.default_rng(seed)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(idx))))
        return pd.DataFrame({"close": close}, index=idx)


def test_weekday_equity_is_not_dropped_for_weekend_gaps_against_btc() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CalendarYf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))

    # Both symbols keep a row in the matrix; the weekend gap is not "null-heavy".
    assert res.data["dropped_symbols"] == []
    assert set(res.data["symbols"]) == {"AAPL", "BTCUSDT"}
    assert res.data["pearson"]["AAPL"]["BTCUSDT"] is not None
    assert not any("null-heavy" in w or "null rows" in w for w in res.warnings)


def test_real_missing_sessions_still_drop_the_symbol() -> None:
    """A weekday series with most of its own trading sessions missing is still dropped."""

    class _SparseYf(_CalendarYf):
        async def fetch(self, request: Any) -> pd.DataFrame:
            frame = await super().fetch(request)
            if request.instrument.symbol == "AAPL":
                # Keep one session in five: 80% of AAPL's own sessions are missing.
                frame = frame.iloc[::5]
            return frame

    fn = CORRFunction(FunctionDeps(yfinance=_SparseYf()))
    res = _run(fn.execute(symbols=["AAPL", "EURUSD", "BTCUSDT"], live_correlation=True, days=120))

    # AAPL is removed from the matrix (dropped as thin or as null-heavy, either way).
    assert "AAPL" not in res.data["symbols"]
    # Full-coverage peers keep their rows; their weekend gaps are calendar only.
    assert "EURUSD" in res.data["symbols"]
    assert "BTCUSDT" in res.data["symbols"]
