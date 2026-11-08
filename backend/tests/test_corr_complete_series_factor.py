"""XCON-7 companion: on a complete (gap-free) series the vol map and the
return-series summary also share one annualization factor. Both paths use
the realized density, which keeps the nominal sqrt(252) for a complete
exchange series (within 5% of 252 a year) and the realized sqrt(n/yr) for a
different calendar (crypto) or a gappy series (XCON-7-RQ). The network is patched; the adapter returns a seeded
series with no missing sessions.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.portfolio.corr import CORRFunction, _realized_annualization_factor
from test_corr_vol_factor_consistency import _find


class _CompleteYf:
    """Every business session present: no calendar gaps."""

    async def fetch(self, request: Any) -> pd.DataFrame:
        sym = request.instrument.symbol
        idx = pd.date_range(end="2026-09-18", periods=500, freq="B")
        seed = sum(ord(ch) for ch in sym)
        rng = np.random.default_rng(seed)
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.01, len(idx))))
        return pd.DataFrame({"close": close}, index=idx)


def test_vol_map_and_return_summary_agree_on_a_complete_series() -> None:
    fn = CORRFunction(FunctionDeps(yfinance=_CompleteYf()))
    res = asyncio.run(fn.execute(symbols=["AAA", "BBB"], live_correlation=True, days=600))

    vol_map = res.data["annualized_vol"]
    summary = _find(res.data, "return_series_summary")
    assert vol_map and summary
    by_symbol = {row["symbol"]: row for row in summary}
    for symbol in ("AAA", "BBB"):
        assert vol_map[symbol] == pytest.approx(by_symbol[symbol]["annualized_volatility"], abs=1e-6), symbol


def test_complete_daily_series_keeps_the_nominal_factor() -> None:
    # XCON-7-RQ: a complete exchange daily series (about 252-261 bars a year)
    # is the nominal calendar, so it keeps sqrt(252) exactly instead of a
    # window-edge density about 2% higher.
    idx = pd.date_range(end="2026-09-18", periods=500, freq="B")
    values = pd.Series(np.zeros(len(idx)), index=idx)
    assert _realized_annualization_factor(values, "daily") == pytest.approx(np.sqrt(252), abs=1e-12)


def test_calendar_daily_series_uses_its_realized_density() -> None:
    # Crypto trades every calendar day: about 365 a year, far outside the band.
    idx = pd.date_range(end="2026-09-18", periods=500, freq="D")
    values = pd.Series(np.zeros(len(idx)), index=idx)
    assert _realized_annualization_factor(values, "daily") == pytest.approx(np.sqrt(365.25), rel=0.01)


def test_gappy_daily_series_uses_its_realized_density() -> None:
    # Every other business day missing: about 130 a year, not 252.
    idx = pd.date_range(end="2026-09-18", periods=1000, freq="B")[::2]
    values = pd.Series(np.zeros(len(idx)), index=idx)
    factor = _realized_annualization_factor(values, "daily")
    assert factor == pytest.approx(np.sqrt(130.5), rel=0.03)
