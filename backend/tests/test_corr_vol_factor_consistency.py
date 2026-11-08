"""XCON-7 regression: CORR must report one annualized vol per symbol.

The vol map used the nominal sqrt(252/52/12) factor while the return-series
summary used the realized observation density (Q3 #22). On a gappy series the
same symbol showed two different annual vols in one response. The network is
patched; the yfinance adapter returns a seeded series with calendar gaps.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.corr import CORRFunction


class _GappyYf:
    """Weekday series with ~30% of sessions missing (a gappy, non-complete series)."""

    async def fetch(self, request: Any) -> pd.DataFrame:
        sym = request.instrument.symbol
        idx = pd.date_range(end="2026-09-18", periods=500, freq="B")
        seed = sum(ord(ch) for ch in sym)
        rng = np.random.default_rng(seed)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(idx))))
        keep = rng.random(len(idx)) > 0.30
        return pd.DataFrame({"close": close[keep]}, index=idx[keep])


def _find(obj: Any, key: str) -> Any:
    """Return the first value stored under ``key`` anywhere in a nested payload."""
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for value in obj.values():
            found = _find(value, key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for value in obj:
            found = _find(value, key)
            if found is not None:
                return found
    return None


def test_vol_map_and_return_summary_agree_on_one_factor() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_GappyYf()))
    res = asyncio.run(fn.execute(symbols=["AAA", "BBB"], live_correlation=True, days=600))

    vol_map = res.data["annualized_vol"]
    summary = _find(res.data, "return_series_summary")
    assert vol_map and summary, "CORR must return both the vol map and the return summary"
    by_symbol = {row["symbol"]: row for row in summary}
    for symbol in ("AAA", "BBB"):
        assert vol_map[symbol] == pytest.approx(by_symbol[symbol]["annualized_volatility"], abs=1e-6), symbol
