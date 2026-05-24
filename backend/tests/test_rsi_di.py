"""Bundle C / C5 regression: RSI's embedded ADX/+DI/-DI computes correctly.

Previously the +DM mask was applied BEFORE the -DM mask was evaluated,
which meant the -DM dominance check ran against an already-zeroed +DM
series — so -DI was almost always overstated and ADX regime detection
flipped to the wrong side on bearish trends.
"""

from __future__ import annotations

import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.indicators.rsi import RSIIndicator  # noqa: E402


def _trending_up_df(n: int = 80) -> pd.DataFrame:
    """Construct a clear uptrend where +DI should dominate."""
    base = np.linspace(100, 200, n) + np.random.default_rng(1).normal(0, 0.5, n)
    return pd.DataFrame(
        {
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base,
            "volume": np.full(n, 1000.0),
        }
    )


def _trending_down_df(n: int = 80) -> pd.DataFrame:
    """Construct a clear downtrend where -DI should dominate."""
    base = np.linspace(200, 100, n) + np.random.default_rng(2).normal(0, 0.5, n)
    return pd.DataFrame(
        {
            "high": base + 1.0,
            "low": base - 1.0,
            "close": base,
            "volume": np.full(n, 1000.0),
        }
    )


def test_plus_di_dominates_uptrend() -> None:
    """C5: on a clean uptrend, +DI must dominate -DI."""
    df = _trending_up_df()
    rsi = RSIIndicator(config={})
    adx, plus_di, minus_di = rsi._compute_adx(df["high"], df["low"], df["close"], period=14)
    assert plus_di > minus_di, f"+DI={plus_di:.2f} should dominate -DI={minus_di:.2f} on uptrend"
    assert adx > 0


def test_minus_di_dominates_downtrend() -> None:
    """C5 most direct test: on a clean downtrend, -DI must dominate +DI.

    This test would FAIL on the pre-fix code because the +DM column was
    zeroed before the -DM dominance check could compare them.
    """
    df = _trending_down_df()
    rsi = RSIIndicator(config={})
    adx, plus_di, minus_di = rsi._compute_adx(df["high"], df["low"], df["close"], period=14)
    assert minus_di > plus_di, (
        f"-DI={minus_di:.2f} should dominate +DI={plus_di:.2f} on downtrend"
    )
    assert adx > 0


def test_rsi_regime_detects_downtrend() -> None:
    """The end-to-end RSI signal must classify a downtrend as TREND regime
    with -DI dominant (i.e. ``plus_di_dominant == False``)."""
    df = _trending_down_df()
    rsi = RSIIndicator(config={})
    result = rsi.calculate(df)
    assert result.raw_values["plus_di_dominant"] is False, (
        f"raw_values={result.raw_values} should show plus_di_dominant=False on downtrend"
    )
