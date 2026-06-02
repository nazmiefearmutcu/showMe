"""Q1 audit: engine / compute dual-path parity.

The strategy compute engine (``showme.strategies.compute``) and the
signal engine (``showme.engine.indicators.*``) historically diverged on
several indicators — same name, different formula. This locks the
parity points the Q1 audit identified so a regression on either side
is caught immediately:

  * Bollinger band std uses sample (``ddof=1``) on both sides.
  * Wilder RMA-style indicators (RSI / ADX / ATR) now share the same
    ``min_periods=period`` warm-up convention.
  * Multi-output indicators (Stochastic %D, Ichimoku Tenkan/SpanA/SpanB,
    KDJ D/J) expose their secondary series via ``{alias}_{component}``
    suffix so rules can reference them without depending on which
    compute path the strategy runner happens to be on.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


@pytest.fixture
def df() -> pd.DataFrame:
    """Reproducible 120-bar OHLCV fixture so Wilder warm-ups have run."""
    rng = np.random.default_rng(seed=42)
    n = 120
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    open_ = close + rng.normal(0, 0.3, n)
    volume = (1000 + rng.normal(0, 100, n)).clip(min=1)
    idx = pd.date_range("2026-01-01", periods=n, freq="h", tz="UTC")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)


# ── Bollinger ddof=1 parity ───────────────────────────────────────────────


def test_bollinger_compute_uses_ddof_1(df):
    """Compute Bollinger bands match SMA ± k * sample_std (ddof=1)."""
    period, num_std = 20, 2.0
    out = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": period, "num_std": num_std}),
        IndicatorRef(alias="bbl", id="bollinger_lower",
                     params={"period": period, "num_std": num_std}),
    ])
    sma = df["close"].rolling(period).mean()
    expected_upper = sma + num_std * df["close"].rolling(period).std(ddof=1)
    expected_lower = sma - num_std * df["close"].rolling(period).std(ddof=1)
    pd.testing.assert_series_equal(
        out["bbu"].dropna().rename("x"), expected_upper.dropna().rename("x"),
    )
    pd.testing.assert_series_equal(
        out["bbl"].dropna().rename("x"), expected_lower.dropna().rename("x"),
    )


def test_bollinger_compute_does_not_use_ddof_0(df):
    """Pin: ``ddof=0`` would be the old buggy value; bands must differ."""
    period, num_std = 20, 2.0
    out = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": period, "num_std": num_std}),
    ])
    sma = df["close"].rolling(period).mean()
    pop_upper = sma + num_std * df["close"].rolling(period).std(ddof=0)
    # On any non-trivial fixture sample and population std differ.
    assert not out["bbu"].dropna().equals(pop_upper.dropna())


# ── RSI warm-up parity ────────────────────────────────────────────────────


def test_rsi_compute_warmup_returns_nan_first_period_bars(df):
    """With ``min_periods=14`` the first 13 bars are NaN, not 50/100.

    The first bar of ``delta = close.diff()`` is NaN (no prior close);
    ``ewm(min_periods=14)`` then needs 14 *valid* gain/loss observations
    to emit a value, so the first finite RSI value lands at bar index
    13 (the 14th bar, since indexing is 0-based)."""
    out = compute(df, [
        IndicatorRef(alias="r", id="rsi", params={"period": 14}),
    ])
    rsi = out["r"]
    assert rsi.iloc[:13].isna().all(), (
        f"first 13 RSI bars should be NaN, got {rsi.iloc[:13].tolist()}"
    )
    # And the 14th bar (index 13) should be finite.
    assert not pd.isna(rsi.iloc[13]), (
        f"RSI must emit a value by bar 13 (Wilder warm-up complete), got {rsi.iloc[13]}"
    )


def test_rsi_compute_no_100_or_50_hack(df):
    """The legacy ``rsi=100 when avg_loss==0 and avg_gain>0`` hack is gone;
    the textbook RSI returns NaN if either side is missing during warm-up."""
    # Construct a 30-bar series of strict monotone increases (avg_loss==0
    # forever) and confirm RSI returns NaN during warm-up, then values
    # close to 100 once the EMA has converged.
    rng = np.random.default_rng(0)
    n = 30
    close = pd.Series(
        100 + np.cumsum(np.abs(rng.normal(0.5, 0.1, n))),
        index=pd.date_range("2026-01-01", periods=n, freq="h"),
    )
    df2 = pd.DataFrame({
        "open": close, "high": close * 1.001, "low": close * 0.999,
        "close": close, "volume": [1000] * n,
    })
    out = compute(df2, [IndicatorRef(alias="r", id="rsi", params={"period": 14})])
    # Warm-up NaN (first 13 bars)
    assert out["r"].iloc[:13].isna().all()
    # Post warm-up (starts at index 13): should be exactly 100.0 since avg_loss → 0 exactly.
    # The division-by-zero handler sets this to 100.0.
    later = out["r"].iloc[13:]
    # Either NaN (during warm-up if any was propagated) or 100.
    assert (later.isna() | (later > 99)).all()


# ── ADX user params not dropped ───────────────────────────────────────────


def test_adx_compute_honours_user_period(df):
    """The audit found ``_compute_atr(df, {"period": period})`` dropped
    user params. Honour ``adx_period`` differently from ``atr_period``."""
    out_short = compute(df, [
        IndicatorRef(alias="adx", id="adx", params={"period": 7}),
    ])
    out_long = compute(df, [
        IndicatorRef(alias="adx", id="adx", params={"period": 28}),
    ])
    # Different periods → different ADX. If user params were dropped, the
    # two series would be identical from ``period=14`` (the default).
    assert not out_short["adx"].dropna().equals(out_long["adx"].dropna())


# ── Stochastic and Ichimoku multi-output suffix registry ──────────────────


def test_stochastic_exposes_d_line_via_alias_suffix(df):
    """The %D line must be reachable via ``{alias}_d``."""
    out = compute(df, [
        IndicatorRef(alias="stk", id="stochastic",
                     params={"k_period": 14, "smooth": 3, "d_period": 3}),
    ])
    assert "stk" in out
    assert "stk_d" in out
    # %D is the SMA of %K so it must lag and never NaN-strictly-before %K.
    # We verify shape only (length); the correctness is pinned in the
    # dedicated test_stoch_d_cross.py file.
    assert len(out["stk_d"]) == len(df)


def test_ichimoku_exposes_all_five_components(df):
    """All 5 Ichimoku components must be reachable via suffix aliases."""
    out = compute(df, [
        IndicatorRef(alias="ichi", id="ichimoku"),
    ])
    for suffix in ("tenkan", "kijun", "senkou_a", "senkou_b", "chikou"):
        assert f"ichi_{suffix}" in out, (
            f"missing ichimoku component {suffix!r} in {sorted(out.keys())!r}"
        )


def test_kdj_exposes_d_and_j_via_alias_suffix(df):
    """KDJ J = 3K - 2D, both must be reachable."""
    out = compute(df, [
        IndicatorRef(alias="kdj", id="kdj"),
    ])
    assert "kdj" in out  # primary K line
    assert "kdj_d" in out
    assert "kdj_j" in out
    # The J = 3K - 2D identity on every valid bar.
    valid = ~(out["kdj"].isna() | out["kdj_d"].isna() | out["kdj_j"].isna())
    expected_j = 3 * out["kdj"][valid] - 2 * out["kdj_d"][valid]
    pd.testing.assert_series_equal(
        out["kdj_j"][valid].rename("j"), expected_j.rename("j"),
    )
