"""Audit Q3 #8 — Backtest fee notional was `cash * 1.0` regardless of pos.

Pin: when flipping a position (pos != 0 → target != 0 or back to 0), the
notional used to size the fee must reflect the absolute position size,
not raw cash.
"""
from __future__ import annotations

import pandas as pd

from showme.engine.services.backtest_framework import Backtest


def _make_bars(closes: list[float]) -> pd.DataFrame:
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes}, index=idx)


def _flip_strategy(bars, state):
    """Cycle through +1 → −1 → +1 …"""
    i = len(bars)
    return 1 if (i % 2 == 0) else -1


def test_fee_charged_per_flip_scaled_by_abs_pos():
    """A 1→-1 flip (|target-pos|=2) should be charged double a 0→1 open."""
    closes = [100.0, 101.0, 102.0, 103.0, 104.0, 105.0, 106.0, 107.0, 108.0]
    bars = _make_bars(closes)
    bt = Backtest(bars, strategy=_flip_strategy, warmup=1,
                  fee_bps=100.0, allow_short=True, initial_cash=10_000.0)
    res = bt.run()
    fees = [t["fee"] for t in res.trades]
    assert len(fees) >= 2
    # First trade should be a 0→±1 OPEN; later trades are flips that span
    # |to-from| = 2, so fee_amt must be at least roughly 2× the per-unit
    # turnover charge.
    open_fee = fees[0]
    flip_fees = [f for f in fees[1:]]
    # If flips are all roughly the same as open we know the legacy
    # `notional = cash * 1.0` bug is back.
    assert max(flip_fees) > open_fee * 1.5, (
        f"flip fees {flip_fees} not larger than open fee {open_fee}; "
        f"notional likely still hardcoded to `cash * 1.0`"
    )
