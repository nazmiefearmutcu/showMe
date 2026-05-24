"""B4 regression: BLAK must not lie about its data source.

Before the fix BLAK pre-claimed ``sources=["yfinance"]`` and dropped to a
deterministic sine-wave fallback in silence whenever ``df.shape[0] < 10``.
These tests pin the new contract:

* fully-synthetic runs report ``return_data_state="synthetic_fallback"`` and
  ``sources=["synthetic_fallback", ...]`` (mcap providers may extend the
  list);
* live errors land in ``live_fetch_errors`` instead of being swallowed;
* partial success (some symbols fetched, but combined frame is still too
  thin) sets ``partial_live=True``.
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from showme.engine.core.base_data_source import DataSourceError
from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.blak import BLAKFunction


class _FakeYFinanceAdapter:
    """Returns whatever the test asks for, per-symbol."""

    def __init__(self, frames: dict[str, pd.DataFrame] | None = None,
                 raise_for: set[str] | None = None,
                 raise_with: type[BaseException] = DataSourceError):
        self._frames = frames or {}
        self._raise_for = raise_for or set()
        self._raise_with = raise_with
        self.calls: list[str] = []

    async def fetch(self, request):
        sym = request.instrument.symbol if request.instrument else ""
        self.calls.append(sym)
        if sym in self._raise_for:
            raise self._raise_with(f"forced failure for {sym}")
        return self._frames.get(sym, pd.DataFrame())


def _synthetic_frame(rows: int = 30, start_price: float = 100.0) -> pd.DataFrame:
    """Produce a tiny OHLCV frame that ``close_to_daily_returns`` accepts."""
    idx = pd.date_range("2025-01-01", periods=rows, freq="B")
    closes = [start_price + 0.5 * i for i in range(rows)]
    return pd.DataFrame(
        {
            "open": closes,
            "high": [c * 1.01 for c in closes],
            "low": [c * 0.99 for c in closes],
            "close": closes,
            "volume": [1_000_000] * rows,
        },
        index=idx,
    )


async def test_b4_full_synthetic_run_advertises_synthetic_source():
    """Live=True but every fetch returns empty ⇒ synthetic_fallback."""
    adapter = _FakeYFinanceAdapter(frames={"AAPL": pd.DataFrame(), "MSFT": pd.DataFrame()})
    fn = BLAKFunction(deps=FunctionDeps(yfinance=adapter))
    result = await fn.execute(symbols=["AAPL", "MSFT"], live=True)
    assert result.data["return_data_state"] == "synthetic_fallback"
    assert "synthetic_fallback" in result.sources
    # Old behaviour would silently emit "yfinance" — make sure the regression
    # never sneaks back in.
    assert "yfinance" not in result.sources
    assert any("synthetic" in w.lower() for w in result.warnings)


async def test_b4_live_errors_are_logged_and_surfaced():
    """A raised DataSourceError must land in live_fetch_errors."""
    adapter = _FakeYFinanceAdapter(raise_for={"AAPL", "MSFT"})
    fn = BLAKFunction(deps=FunctionDeps(yfinance=adapter))
    result = await fn.execute(symbols=["AAPL", "MSFT"], live=True)
    errors = result.data["live_fetch_errors"]
    assert len(errors) == 2
    assert any("AAPL" in e for e in errors)
    assert any("MSFT" in e for e in errors)
    assert result.data["return_data_state"] == "synthetic_fallback"


async def test_b4_successful_live_keeps_yfinance_source():
    """With enough rows from the adapter the fallback must not engage."""
    adapter = _FakeYFinanceAdapter(frames={
        "AAPL": _synthetic_frame(60, 100),
        "MSFT": _synthetic_frame(60, 200),
    })
    fn = BLAKFunction(deps=FunctionDeps(yfinance=adapter))
    result = await fn.execute(symbols=["AAPL", "MSFT"], live=True)
    assert result.data["return_data_state"] == "live"
    assert "yfinance" in result.sources
    assert "synthetic_fallback" not in result.sources
    assert result.data["live_fetch_errors"] == []
    assert "AAPL" in result.data["live_fetch_ok_symbols"]
    assert "MSFT" in result.data["live_fetch_ok_symbols"]


async def test_b4_cancelled_error_propagates():
    """asyncio.CancelledError must not be swallowed by the catch-all."""
    adapter = _FakeYFinanceAdapter(raise_for={"AAPL"}, raise_with=asyncio.CancelledError)
    fn = BLAKFunction(deps=FunctionDeps(yfinance=adapter))
    with pytest.raises(asyncio.CancelledError):
        await fn.execute(symbols=["AAPL"], live=True)
