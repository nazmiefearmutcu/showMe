"""Audit Q3 #6 — CAGR exponent must use the *realized* elapsed years
between first and last bar, not the request window.

Repro: ask TRA for `years=5`, yfinance returns 2 years of history
(young ticker). The legacy code did
    (last/first) ** (1/5) − 1
which understates CAGR by ~40% when actual span is 2y.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.portfolio._more import TRAFunction


def _make_price_series(years_actual: float, total_return: float) -> pd.DataFrame:
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    start = end - timedelta(days=int(years_actual * 365.25))
    idx = pd.date_range(start, end, freq="B")
    n = len(idx)
    # Geometric growth from 100 to 100*(1+total_return)
    factor = (1.0 + total_return) ** (1.0 / max(n - 1, 1))
    closes = 100.0 * (factor ** pd.Series(range(n), index=idx))
    return pd.DataFrame({"close": closes, "dividends": [0.0] * n})


class _FakeYf:
    """Minimal yfinance adapter that returns a pre-baked frame."""

    def __init__(self, df: pd.DataFrame) -> None:
        self._df = df

    async def fetch(self, request):  # noqa: ARG002
        return self._df


@pytest.mark.asyncio
async def test_cagr_uses_actual_years_when_history_is_short():
    # 2 years of history, total +21% (i.e. ~10% CAGR over 2y)
    df = _make_price_series(years_actual=2.0, total_return=0.21)
    deps = FunctionDeps(yfinance=_FakeYf(df))
    fn = TRAFunction(deps)
    instrument = Instrument(symbol="YOUNG", asset_class=AssetClass.EQUITY)
    # Request 5 years even though only 2y exist.
    res = await fn.execute(instrument=instrument, years=5, live=True)
    cagr = res.data["cagr"]
    # Actual 2y CAGR should be sqrt(1.21) − 1 ≈ 10%, NOT (1.21)**(1/5) − 1 ≈ 3.9%
    assert cagr is not None
    assert 0.085 < cagr < 0.115, f"CAGR={cagr:.4f} not in 8.5–11.5% range"


@pytest.mark.asyncio
async def test_cagr_matches_requested_years_when_history_is_full():
    df = _make_price_series(years_actual=5.0, total_return=0.611)  # 10% CAGR over 5y
    deps = FunctionDeps(yfinance=_FakeYf(df))
    fn = TRAFunction(deps)
    instrument = Instrument(symbol="FULL", asset_class=AssetClass.EQUITY)
    res = await fn.execute(instrument=instrument, years=5, live=True)
    cagr = res.data["cagr"]
    assert cagr is not None
    assert 0.092 < cagr < 0.108, f"CAGR={cagr:.4f} not ~10%"
