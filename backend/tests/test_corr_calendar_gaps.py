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


def _drop_weekday_positions(frame: pd.DataFrame, positions: list[int]) -> pd.DataFrame:
    return frame.drop(frame.index[positions])


def test_a_few_holiday_weekdays_do_not_drop_a_full_coverage_symbol() -> None:
    """Holidays are real missing sessions, but five of about 160 is far below 30%."""

    class _HolidayYf(_CalendarYf):
        async def fetch(self, request: Any) -> pd.DataFrame:
            frame = await super().fetch(request)
            if request.instrument.symbol == "AAPL":
                frame = _drop_weekday_positions(frame, [10, 40, 70, 100, 130])
            return frame

    fn = CORRFunction(FunctionDeps(yfinance=_HolidayYf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))

    assert res.data["dropped_symbols"] == []
    assert "AAPL" in res.data["symbols"]


def test_missing_weekday_sessions_are_reported_with_holidays_counted() -> None:
    """40% of AAPL's own weekday sessions missing: dropped, and the message must not
    claim holidays are excluded from the count (the code counts them)."""

    class _Holey40Yf(_CalendarYf):
        async def fetch(self, request: Any) -> pd.DataFrame:
            frame = await super().fetch(request)
            if request.instrument.symbol == "AAPL":
                frame = _drop_weekday_positions(frame, [i for i in range(len(frame)) if i % 5 in (0, 1)])
            return frame

    fn = CORRFunction(FunctionDeps(yfinance=_Holey40Yf()))
    res = _run(fn.execute(symbols=["AAPL", "BTCUSDT"], live_correlation=True, days=120))

    assert "AAPL" in res.data["dropped_symbols"]
    message = res.data["coverage_status"]["AAPL"]["message"]
    assert "Weekend and holiday gaps are not counted" not in message
    assert "holiday" in message.lower()
    assert "weekend gaps" in message.lower()
    warning = next(w for w in res.warnings if "AAPL" in w)
    assert "trading sessions" in warning
    assert "null-heavy" not in warning


def test_forward_fill_still_drops_a_symbol_missing_most_of_its_real_sessions() -> None:
    """Pinned decision: under forward_fill the drop test still uses each symbol's own
    raw session gaps, so carried-forward closes cannot keep a mostly-missing series."""

    class _SparseYf(_CalendarYf):
        async def fetch(self, request: Any) -> pd.DataFrame:
            frame = await super().fetch(request)
            if request.instrument.symbol == "AAPL":
                frame = frame.iloc[::5]
            return frame

    fn = CORRFunction(FunctionDeps(yfinance=_SparseYf()))
    res = _run(fn.execute(
        symbols=["AAPL", "EURUSD", "BTCUSDT"], live_correlation=True, days=120,
        missing_data_policy="forward_fill",
    ))

    assert "AAPL" in res.data["dropped_symbols"]
    assert "AAPL" not in res.data["symbols"]
    assert "EURUSD" in res.data["symbols"]
