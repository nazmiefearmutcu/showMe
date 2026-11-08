"""TECH ADX must follow Wilder's directional-movement rule.

Wilder: on each bar only the LARGER of +DM and -DM counts (and only if it is
positive); the other is zeroed. The pre-fix ``_adx`` clipped each side
independently, so on "outside" bars (both DMs positive) both DI lines
inflated and the ADX drifted from the textbook value.

The reference below is an independent textbook implementation; the test runs
TECHFunction.execute() with the yfinance adapter stubbed (no network).
"""

from __future__ import annotations

import asyncio
import random
from typing import Any

import numpy as np
import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.chart.tech import TECHFunction

EQ = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


def _synthetic_ohlc(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = random.Random(seed)
    closes = [100.0]
    for _ in range(n - 1):
        closes.append(closes[-1] * (1.0 + rng.gauss(0.0, 0.012)))
    rows = []
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i else close
        opened = prev * (1.0 + rng.gauss(0.0, 0.004))
        high = max(opened, close) * (1.0 + abs(rng.gauss(0.0, 0.009)))
        low = min(opened, close) * (1.0 - abs(rng.gauss(0.0, 0.009)))
        rows.append((opened, high, low, close, 1_000_000.0 + rng.random() * 1e5))
    index = pd.date_range("2024-01-01", periods=n, freq="D")
    return pd.DataFrame(rows, index=index, columns=["open", "high", "low", "close", "volume"])


def _textbook_adx(df: pd.DataFrame, period: int = 14) -> tuple[float, int]:
    """Wilder ADX with the exclusive directional-movement rule.

    Returns (last ADX, number of bars where both raw DMs were positive).
    """
    highs = df["high"].to_numpy(dtype=float)
    lows = df["low"].to_numpy(dtype=float)
    closes = df["close"].to_numpy(dtype=float)
    n = len(closes)
    tr = np.zeros(n)
    plus = np.zeros(n)
    minus = np.zeros(n)
    tr[0] = highs[0] - lows[0]
    outside = 0
    for i in range(1, n):
        up = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > 0 and down > 0:
            outside += 1
        plus[i] = up if (up > down and up > 0) else 0.0
        minus[i] = down if (down > up and down > 0) else 0.0
        tr[i] = max(highs[i] - lows[i], abs(highs[i] - closes[i - 1]), abs(lows[i] - closes[i - 1]))

    alpha = 1.0 / period

    def rma(values: np.ndarray) -> np.ndarray:
        out = np.zeros(n)
        out[0] = values[0]
        for i in range(1, n):
            out[i] = alpha * values[i] + (1 - alpha) * out[i - 1]
        return out

    atr = rma(tr)
    plus_di = 100 * rma(plus) / atr
    minus_di = 100 * rma(minus) / atr
    di_sum = plus_di + minus_di
    dx = np.zeros(n)
    nonzero = di_sum > 0
    dx[nonzero] = 100 * np.abs(plus_di[nonzero] - minus_di[nonzero]) / di_sum[nonzero]
    adx = rma(dx)
    return float(adx[-1]), outside


class _SyntheticYfinance:
    def __init__(self, frame: pd.DataFrame) -> None:
        self._frame = frame

    async def fetch(self, *args: Any, **kwargs: Any) -> pd.DataFrame:
        return self._frame.copy()


def test_tech_adx_matches_wilder_exclusive_dm_rule() -> None:
    frame = _synthetic_ohlc()
    expected, outside_bars = _textbook_adx(frame, 14)
    # The fixture must actually exercise the bug (bars where both DMs are positive).
    assert outside_bars > 0

    fn = TECHFunction(FunctionDeps(yfinance=_SyntheticYfinance(frame)))
    out = asyncio.run(fn.execute(instrument=EQ, interval="1d"))
    got = out.data["summary"]["adx"]

    assert got is not None
    assert got == pytest.approx(expected, abs=1e-6), (
        f"TECH ADX {got!r} != Wilder reference {expected!r}"
    )
    # The per-row series must agree with the summary on the last bar.
    assert out.data["rows"][-1]["adx"] == pytest.approx(expected, abs=1e-6)
