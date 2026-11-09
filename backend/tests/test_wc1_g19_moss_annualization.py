"""WC1-G19 XCON-1: MOSS annualizes crypto daily vol with 365 periods, exchange assets with 252.

Crypto trades every calendar day, so its daily closes run 365 a year; ANR already uses
sqrt(365) for crypto. No network: the market-data adapter is a deterministic fake.
"""

from __future__ import annotations

import asyncio
from typing import Any

import numpy as np
import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc import _bonus


class _SameReturnsYfinance:
    """Same daily return path for every symbol, on a calendar-day index."""

    async def fetch(self, request: Any, *_args: Any, **_kwargs: Any) -> pd.DataFrame:
        rng = np.random.default_rng(7)
        n = 120
        close = 100.0 * np.exp(np.cumsum(rng.normal(0.0, 0.02, n)))
        idx = pd.date_range(end="2026-10-30", periods=n, freq="D")
        return pd.DataFrame({"close": close}, index=idx)


def test_moss_annualizes_crypto_with_365_and_exchange_assets_with_252() -> None:
    out = asyncio.run(
        _bonus.MOSSFunction(FunctionDeps(yfinance=_SameReturnsYfinance())).execute(
            universe="BTC-USD,AAPL", days=90
        )
    )
    rows = {row["symbol"]: row for row in out.data["rows"]}
    btc, aapl = rows["BTC-USD"], rows["AAPL"]
    assert btc["periods_per_year"] == 365
    assert aapl["periods_per_year"] == 252
    # Identical returns: the ratio is exactly sqrt(365/252) once the factor differs.
    ratio = btc["vol_annualized"] / aapl["vol_annualized"]
    assert abs(ratio - (365 / 252) ** 0.5) < 1e-9, ratio
    assert "sqrt(365)" in out.data["methodology"]
