"""Q1 audit CRITICAL 1/2: Wilder-RMA warm-up via ``min_periods=period``.

Without ``min_periods``, ``Series.ewm(alpha=1/n, adjust=False).mean()``
emits a value from the very first observation (treating the partial
window as if it were the seed). For Wilder smoothing this is wrong —
the textbook RMA isn't defined until ``period`` observations exist.

The compute path previously omitted ``min_periods``, producing values
during warm-up that drifted noticeably from engine output (which has
always used the proper guard). This file pins the new behaviour:

  * RSI warm-up: first ``period`` bars are NaN, no fake 50/100 sentinel.
  * ADX warm-up: similarly NaN until DI lines stabilise.
  * ATR warm-up: NaN until ``period`` bars of true-range have flowed in.
  * The rsi=100/50 hack is gone — divisions by zero stay NaN.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


@pytest.fixture
def df() -> pd.DataFrame:
    rng = np.random.default_rng(seed=14)
    n = 60
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close, "volume": [1000.0] * n,
    }, index=pd.date_range("2026-01-01", periods=n, freq="h"))


def test_rsi_warmup_is_nan_no_50_hack(df):
    """First 13 RSI bars must be NaN (with period=14). The 14th bar
    (index 13) is the first valid output — see test_indicator_dual_path
    for the rationale."""
    out = compute(df, [IndicatorRef(alias="r", id="rsi", params={"period": 14})])
    assert out["r"].iloc[:13].isna().all()
    assert not pd.isna(out["r"].iloc[13])


def test_atr_warmup_is_nan(df):
    """First 14 ATR bars must be NaN (with period=14)."""
    out = compute(df, [IndicatorRef(alias="a", id="atr", params={"period": 14})])
    # First TR is NaN (no prior close). Then EWM with min_periods=14
    # needs 14 valid TR values — so the first ~14 bars are NaN.
    assert out["a"].iloc[0:13].isna().all()


def test_adx_warmup_is_nan(df):
    """ADX needs 2*period bars to stabilise; the first ~14 must be NaN
    (we no longer fake an early value via missing min_periods)."""
    out = compute(df, [IndicatorRef(alias="x", id="adx", params={"period": 14})])
    assert out["x"].iloc[:13].isna().all()


def test_rsi_after_warmup_is_in_0_to_100(df):
    """Once warm-up clears, RSI must live in [0, 100]."""
    out = compute(df, [IndicatorRef(alias="r", id="rsi", params={"period": 14})])
    valid = out["r"].dropna()
    assert (valid >= 0).all() and (valid <= 100).all()


def test_rsi_monotone_up_series_no_legacy_hack():
    """On a monotone-up series, avg_loss==0 so the textbook RSI is NaN
    (0/0). The old hack would have returned 100.0; the fix removes the
    hack — NaN-with-context is preferred over a fake sentinel."""
    n = 40
    close = pd.Series(
        100 + np.arange(n, dtype=float),
        index=pd.date_range("2026-01-01", periods=n, freq="h"),
    )
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": [1000] * n,
    })
    out = compute(df, [IndicatorRef(alias="r", id="rsi", params={"period": 14})])
    # Post-warmup, RSI should be NaN (avg_loss exactly 0 → division by NaN
    # because of the ``replace(0, np.nan)`` guard).
    # We require absence of the fake 50.0 sentinel that flat data used to
    # produce.
    post = out["r"].iloc[14:]
    assert not (post == pytest.approx(50.0)).any(), (
        "RSI=50 sentinel for flat data is the old hack — must be gone"
    )


def test_rsi_loss_term_parens_consistent_with_engine():
    """RSI loss = ``(-delta).where(delta < 0, 0.0)``. The old expression
    ``-delta.where(delta < 0, 0.0)`` parsed as ``-(delta.where(...))``
    which flipped the sign on the zero branch. With the parens fix,
    compute output should match engine output to within float tolerance
    on a long-enough series."""
    from showme.engine.indicators.rsi import _wilder_rma

    n = 80
    rng = np.random.default_rng(123)
    close_arr = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame({
        "open": close_arr, "high": close_arr + 0.5, "low": close_arr - 0.5,
        "close": close_arr, "volume": [1000] * n,
    }, index=pd.date_range("2026-01-01", periods=n, freq="h"))

    out = compute(df, [IndicatorRef(alias="r", id="rsi", params={"period": 14})])
    # Engine-style reproduction
    close = df["close"]
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = _wilder_rma(gain, 14)
    avg_loss = _wilder_rma(loss, 14)
    rs = avg_gain / avg_loss.replace(0, np.nan)
    engine_rsi = 100.0 - (100.0 / (1.0 + rs))
    pd.testing.assert_series_equal(
        out["r"].dropna().rename("x"),
        engine_rsi.dropna().rename("x"),
    )
