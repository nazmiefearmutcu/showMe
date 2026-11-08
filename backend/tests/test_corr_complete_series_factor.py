"""XCON-7 companion: on a complete (gap-free) series the vol map and the
return-series summary also share one annualization factor. The realized
factor sqrt(observations per year) is used on both paths, so for a complete
daily series it lands close to the nominal sqrt(252) but is no longer the
nominal value itself. The network is patched; the adapter returns a seeded
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


def test_complete_daily_series_factor_stays_within_a_few_percent_of_nominal() -> None:
    # 500 business days over the calendar span is about 256 per year, so the
    # realized factor sits about 2% above sqrt(252) for an equity daily series.
    # This pins the bounded size of the XCON-7 shift on complete series.
    idx = pd.date_range(end="2026-09-18", periods=500, freq="B")
    values = pd.Series(np.zeros(len(idx)), index=idx)
    factor = _realized_annualization_factor(values, "daily")
    assert factor == pytest.approx(np.sqrt(252), rel=0.03)
