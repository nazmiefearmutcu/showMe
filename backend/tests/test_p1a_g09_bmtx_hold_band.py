"""BMTX#1 regression: rsi_meanrev must hold a long between its thresholds.

The strategy keeps its position in ``state["pos"]`` and returns it while RSI
sits between ``lo`` and ``hi``. The engine used to never write that key, so the
between-thresholds branch always returned 0 and a long opened below ``lo`` was
flattened as soon as RSI crossed back above ``lo``. The fix is that the engine
publishes the held position into ``state`` before every decision.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "backend"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.services.backtest_framework import (  # noqa: E402
    Backtest,
    rsi_meanrev,
)


def _bars() -> pd.DataFrame:
    closes = [100.0]
    for _ in range(25):  # sharp selloff -> RSI collapses, long is opened
        closes.append(closes[-1] - 1.5)
    for i in range(40):  # sideways chop -> RSI recovers into the 30-70 band
        closes.append(closes[-1] + (0.9 if i % 2 == 0 else -0.5))
    idx = pd.date_range("2024-01-01", periods=len(closes), freq="B")
    return pd.DataFrame({"close": closes}, index=idx)


def _rsi_series(bars: pd.DataFrame, period: int = 14) -> pd.Series:
    delta = bars["close"].diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / period, adjust=False).mean()
    loss = -delta.clip(upper=0).ewm(alpha=1 / period, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


def test_rsi_meanrev_long_is_held_inside_band() -> None:
    bars = _bars()
    rsi = _rsi_series(bars)
    res = Backtest(bars, rsi_meanrev, warmup=5, fee_bps=0.0).run()

    opens = [t for t in res.trades if t["from"] == 0 and t["to"] == 1]
    closes = [t for t in res.trades if t["from"] == 1 and t["to"] == 0]
    assert opens, "strategy should open a long on the selloff"

    # Every exit must happen only once RSI has crossed the upper threshold (70).
    # Before the fix the long was closed at an RSI of ~55, inside the hold band.
    for trade in closes:
        ts = pd.Timestamp(trade["ts"])
        rsi_at_exit = float(rsi.loc[ts])
        assert rsi_at_exit > 70.0, (
            f"long closed at RSI {rsi_at_exit:.2f} inside the 30-70 hold band "
            f"(trade={trade})"
        )


def test_engine_publishes_held_position_into_state() -> None:
    """The strategy must be able to read the position it currently holds."""
    bars = _bars()
    seen: list[int] = []

    def probe(_window: pd.DataFrame, state: dict) -> int:
        seen.append(int(state.get("pos", 0)))
        return 1 if len(seen) <= 3 else 1

    Backtest(bars, probe, warmup=5, fee_bps=0.0).run()
    # Once a long is held, the next decision must see pos == 1, not the default 0.
    assert seen[0] == 0
    assert all(p == 1 for p in seen[3:]), seen
