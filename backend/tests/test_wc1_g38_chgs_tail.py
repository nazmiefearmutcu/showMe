"""CHGS#2 — a routed agent default ``limit=6`` must not shrink the 1Y chart.

The router merges agent-profile defaults (``limit=6``, ``range=3M``) into every
CHGS call. TECH reads ``limit`` as the bar tail and clamps it to 60..5000, so a
1Y request (``days=365``) came back with only 60 bars. CHGS has no tail/limit
input of its own; its window is driven by ``days``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pandas as pd

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.engine.core.base_function import FunctionDeps  # noqa: E402
from showme.engine.core.instrument import AssetClass, Instrument  # noqa: E402
from showme.engine.functions.misc._bonus import CHGSFunction  # noqa: E402

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _FakeYfinance:
    """Deterministic daily OHLCV fixture (no network)."""

    def __init__(self, bars: int = 400) -> None:
        self._bars = bars

    async def fetch(self, request):  # noqa: ANN001 - fake seam
        rng = np.random.default_rng(11)
        close = 100 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, size=self._bars)))
        idx = pd.bdate_range(end="2026-09-18", periods=self._bars)
        return pd.DataFrame({
            "open": close * 0.999,
            "high": close * 1.01,
            "low": close * 0.99,
            "close": close,
            "volume": np.full(self._bars, 1_000_000.0),
        }, index=idx)


def _run(coro):
    return asyncio.run(coro)


def test_chgs_routed_limit_default_does_not_clamp_the_bar_series() -> None:
    fn = CHGSFunction(FunctionDeps(yfinance=_FakeYfinance(bars=400)))
    # The exact params the router leaks into a CHGS call for a 1Y view.
    result = _run(fn.execute(instrument=AAPL, days=365, limit=6, range="3M",
                             interval="1d", timeout=3))
    bars = result.data["bars"]
    assert len(bars) > 60, f"routed limit=6 clamped the series to {len(bars)} bars"
    assert result.data["bar_count"] == len(bars)


def test_chgs_explicit_tail_is_still_honoured() -> None:
    fn = CHGSFunction(FunctionDeps(yfinance=_FakeYfinance(bars=400)))
    result = _run(fn.execute(instrument=AAPL, days=365, tail=120))
    assert len(result.data["bars"]) == 120
