"""Faz 1 regression tests — indicator output completeness + PSAR seed.

Covers:
* H-14 — equals_approximately handles right=0 correctly: absolute-tolerance
  fallback when the divisor is zero, instead of producing NaN.
* H-16 — bollinger_bands family exposes upper / lower bands as separate ids.
* H-17 — macd family exposes signal line and histogram as separate ids.
* H-18 — parabolic SAR uses textbook two-bar seed (no silent fallback).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


@pytest.fixture
def df() -> pd.DataFrame:
    """Stable 60-bar OHLCV fixture mirroring test_compute.py."""
    rng = np.random.default_rng(seed=42)
    n = 60
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    open_ = close + rng.normal(0, 0.3, n)
    volume = (1000 + rng.normal(0, 100, n)).clip(min=1)
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)


# ── H-14: equals_approximately handles right=0 with absolute tolerance ───


def test_h14_equals_approximately_right_zero_left_within_abs_tolerance():
    """``equals_approximately(0.005, 0, tol=0.01)`` must be True via
    absolute tolerance — the original ratio-based formula produced NaN."""
    from showme.strategies.evaluate import evaluate
    from showme.strategies.spec import Rule, StrategySpec

    spec = StrategySpec(
        name="zero_target",
        entry_rules=[Rule(kind="equals_approximately",
                          left="literal:0.005", right="literal:0",
                          tolerance=0.01)],
        exit_rules=[],
    )
    df = pd.DataFrame({
        "open": [1.0], "high": [1.5], "low": [0.5],
        "close": [1.0], "volume": [1000.0],
    }, index=pd.date_range("2026-05-22", periods=1, freq="h"))
    events = evaluate(spec, df)
    assert len(events) == 1
    assert events[0].kind == "entry"


def test_h14_equals_approximately_right_zero_left_outside_abs_tolerance():
    """``equals_approximately(1, 0, tol=0.01)`` must be False — abs(1) > 0.01."""
    from showme.strategies.evaluate import evaluate
    from showme.strategies.spec import Rule, StrategySpec

    spec = StrategySpec(
        name="zero_target",
        entry_rules=[Rule(kind="equals_approximately",
                          left="literal:1", right="literal:0",
                          tolerance=0.01)],
        exit_rules=[],
    )
    df = pd.DataFrame({
        "open": [1.0], "high": [1.5], "low": [0.5],
        "close": [1.0], "volume": [1000.0],
    }, index=pd.date_range("2026-05-22", periods=1, freq="h"))
    events = evaluate(spec, df)
    assert events == []


def test_h14_equals_approximately_normal_right_non_zero_still_relative():
    """Non-zero ``right`` keeps the original relative-tolerance semantics."""
    from showme.strategies.evaluate import evaluate
    from showme.strategies.spec import Rule, StrategySpec

    spec = StrategySpec(
        name="rel",
        entry_rules=[Rule(kind="equals_approximately",
                          left="literal:101", right="literal:100",
                          tolerance=0.05)],
        exit_rules=[],
    )
    df = pd.DataFrame({
        "open": [1.0], "high": [1.5], "low": [0.5],
        "close": [1.0], "volume": [1000.0],
    }, index=pd.date_range("2026-05-22", periods=1, freq="h"))
    # |101-100| / |100| = 0.01 < 0.05 → True (relative-tolerance branch).
    events = evaluate(spec, df)
    assert len(events) == 1


def test_h14_negative_tolerance_collapses_to_false():
    """Hardening: a negative tolerance never matches (instead of triggering
    the ratio formula's NaN-vs-bool ambiguity)."""
    from showme.strategies.evaluate import evaluate
    from showme.strategies.spec import Rule, StrategySpec

    spec = StrategySpec(
        name="neg",
        entry_rules=[Rule(kind="equals_approximately",
                          left="literal:0", right="literal:0",
                          tolerance=-0.5)],
        exit_rules=[],
    )
    df = pd.DataFrame({
        "open": [1.0], "high": [1.5], "low": [0.5],
        "close": [1.0], "volume": [1000.0],
    }, index=pd.date_range("2026-05-22", periods=1, freq="h"))
    events = evaluate(spec, df)
    assert events == []


# ── H-16: bollinger upper / lower bands ──────────────────────────────────


def test_h16_bollinger_upper_lower_match_sma_plus_minus_std(df):
    """Upper band = SMA + num_std * std; lower band = SMA - num_std * std.

    Q1 CRITICAL fix: std uses ``ddof=1`` (sample std) to match
    Bollinger (1980) and the engine ``bollinger.py`` path. The old
    ``ddof=0`` made compute/engine return different values for every
    bar — dual-path divergence that silently broke rules referencing
    BBU/BBL from either side."""
    period = 20
    num_std = 2.0
    out = compute(df, [
        IndicatorRef(alias="bbm", id="bollinger_bands",
                     params={"period": period}),
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": period, "num_std": num_std}),
        IndicatorRef(alias="bbl", id="bollinger_lower",
                     params={"period": period, "num_std": num_std}),
    ])
    sma = df["close"].rolling(period).mean()
    std = df["close"].rolling(period).std(ddof=1)
    expected_upper = sma + num_std * std
    expected_lower = sma - num_std * std
    # Drop the NaN warm-up rows from both sides for comparison.
    pd.testing.assert_series_equal(
        out["bbu"].dropna().rename("x"),
        expected_upper.dropna().rename("x"),
    )
    pd.testing.assert_series_equal(
        out["bbl"].dropna().rename("x"),
        expected_lower.dropna().rename("x"),
    )


def test_h16_bollinger_upper_above_midline_above_lower(df):
    """Sanity: upper >= midline >= lower at every non-NaN bar."""
    out = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper"),
        IndicatorRef(alias="bbm", id="bollinger_bands"),
        IndicatorRef(alias="bbl", id="bollinger_lower"),
    ])
    valid = ~(out["bbu"].isna() | out["bbm"].isna() | out["bbl"].isna())
    assert (out["bbu"][valid] >= out["bbm"][valid]).all()
    assert (out["bbm"][valid] >= out["bbl"][valid]).all()


def test_h16_bollinger_num_std_param_respected(df):
    """num_std=1 produces tighter bands than num_std=3 at every bar."""
    period = 20
    out_tight = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": period, "num_std": 1.0}),
    ])
    out_wide = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": period, "num_std": 3.0}),
    ])
    valid = ~(out_tight["bbu"].isna() | out_wide["bbu"].isna())
    # Wider band is strictly higher (assuming positive std).
    assert (out_wide["bbu"][valid] >= out_tight["bbu"][valid]).all()


# ── H-17: MACD signal + histogram ────────────────────────────────────────


def test_h17_macd_signal_is_ema_of_macd(df):
    """MACD signal = EMA(signal_period) of the MACD line."""
    out = compute(df, [
        IndicatorRef(alias="macd", id="macd",
                     params={"fast_period": 12, "slow_period": 26,
                             "signal_period": 9}),
        IndicatorRef(alias="signal", id="macd_signal",
                     params={"fast_period": 12, "slow_period": 26,
                             "signal_period": 9}),
    ])
    expected_signal = out["macd"].ewm(span=9, adjust=False).mean()
    pd.testing.assert_series_equal(
        out["signal"].rename("x"),
        expected_signal.rename("x"),
    )


def test_h17_macd_hist_equals_macd_minus_signal(df):
    """Histogram is the difference between MACD and signal."""
    out = compute(df, [
        IndicatorRef(alias="macd", id="macd",
                     params={"fast_period": 12, "slow_period": 26,
                             "signal_period": 9}),
        IndicatorRef(alias="signal", id="macd_signal",
                     params={"fast_period": 12, "slow_period": 26,
                             "signal_period": 9}),
        IndicatorRef(alias="hist", id="macd_hist",
                     params={"fast_period": 12, "slow_period": 26,
                             "signal_period": 9}),
    ])
    pd.testing.assert_series_equal(
        out["hist"].rename("x"),
        (out["macd"] - out["signal"]).rename("x"),
    )


def test_h17_macd_hist_changes_sign_at_macd_signal_cross(df):
    """When MACD crosses its signal line, the histogram changes sign.
    This is the foundational property of MACD-based entries."""
    out = compute(df, [
        IndicatorRef(alias="macd", id="macd"),
        IndicatorRef(alias="signal", id="macd_signal"),
        IndicatorRef(alias="hist", id="macd_hist"),
    ])
    # Hist > 0 iff macd > signal.
    valid = ~out["hist"].isna()
    hist_sign = np.sign(out["hist"][valid])
    diff_sign = np.sign((out["macd"] - out["signal"])[valid])
    assert (hist_sign == diff_sign).all()


# ── H-18: parabolic SAR seed is textbook-correct ─────────────────────────


def test_h18_psar_first_value_seeds_to_first_bar_low(df):
    """Initial SAR equals the first bar's low (uptrend assumption)."""
    out = compute(df, [IndicatorRef(alias="p", id="parabolic_sar")])
    assert out["p"].iloc[0] == pytest.approx(df["low"].iloc[0])


def test_h18_psar_second_bar_uses_single_bar_cap_only():
    """At i=1 there's no low[i-2] in the textbook recurrence; the fix
    must use only ``low[i-1]`` as the cap (not silently substitute
    ``low[i-1]`` for the missing ``low[i-2]``, which the original code
    did and produced subtly wrong SARs)."""
    # Hand-rolled 5-bar OHLCV. Closes don't matter; PSAR uses high/low.
    df = pd.DataFrame({
        "open":   [10.0, 11.0, 12.0, 13.0, 14.0],
        "high":   [11.0, 12.0, 13.0, 14.0, 15.0],
        "low":    [9.0,  10.0, 11.0, 12.0, 13.0],
        "close":  [10.5, 11.5, 12.5, 13.5, 14.5],
        "volume": [1000] * 5,
    }, index=pd.date_range("2026-01-01", periods=5, freq="h"))
    out = compute(df, [IndicatorRef(alias="p", id="parabolic_sar",
                                     params={"af_start": 0.02,
                                             "af_step": 0.02,
                                             "af_max": 0.20})])
    # Reference calculation for an uptrend-only series:
    #   sar[0] = low[0] = 9.0
    #   af0    = 0.02; ep0 = high[0] = 11.0
    # i=1: new_sar = sar[0] + af * (ep - sar[0])
    #             = 9 + 0.02 * (11 - 9) = 9.04
    #     i < 2 → cap = min(new_sar, low[i-1]) = min(9.04, 9) = 9.0
    #     low[1]=10 >= 9.0 → stay up; high[1]=12 > ep=11 → ep=12, af=0.04
    # i=2: new_sar = 9 + 0.04 * (12 - 9) = 9.12
    #     cap = min(9.12, low[1]=10, low[0]=9) = 9.0
    #     low[2]=11 >= 9.0 → stay up; high[2]=13 > ep=12 → ep=13, af=0.06
    # Assertions: sar[1] ≈ 9.0; sar[2] ≈ 9.0.
    assert out["p"].iloc[1] == pytest.approx(9.0)
    assert out["p"].iloc[2] == pytest.approx(9.0)


def test_h18_psar_full_textbook_walkthrough_short_series():
    """Pin five hand-computed bars against the implementation. If anyone
    changes the seed back to the buggy lookback, this fails."""
    # Trending up monotonically: every bar's low is strictly above the
    # previous SAR, so we never flip to downtrend in this fixture.
    df = pd.DataFrame({
        "open":   [10.0, 11.0, 12.0, 13.0, 14.0],
        "high":   [11.0, 12.0, 13.0, 14.0, 15.0],
        "low":    [9.0,  10.0, 11.0, 12.0, 13.0],
        "close":  [10.5, 11.5, 12.5, 13.5, 14.5],
        "volume": [1000] * 5,
    }, index=pd.date_range("2026-01-01", periods=5, freq="h"))
    out = compute(df, [IndicatorRef(alias="p", id="parabolic_sar",
                                     params={"af_start": 0.02,
                                             "af_step": 0.02,
                                             "af_max": 0.20})])
    # i=3: sar[2]=9.0, ep=13, af=0.06
    #     new_sar = 9 + 0.06 * (13 - 9) = 9.24
    #     cap = min(9.24, low[2]=11, low[1]=10) = 9.24
    #     low[3]=12 >= 9.24 → stay up; high[3]=14 > ep=13 → ep=14, af=0.08
    # i=4: sar[3]=9.24, ep=14, af=0.08
    #     new_sar = 9.24 + 0.08 * (14 - 9.24) = 9.6208
    #     cap = min(9.6208, low[3]=12, low[2]=11) = 9.6208
    #     low[4]=13 >= 9.6208 → stay up
    assert out["p"].iloc[3] == pytest.approx(9.24)
    assert out["p"].iloc[4] == pytest.approx(9.6208, rel=1e-6)


def test_h18_psar_handles_single_bar():
    """Single-bar input must not raise; SAR is NaN by convention."""
    df = pd.DataFrame({
        "open": [10.0], "high": [11.0], "low": [9.0],
        "close": [10.5], "volume": [1000],
    }, index=pd.date_range("2026-01-01", periods=1, freq="h"))
    out = compute(df, [IndicatorRef(alias="p", id="parabolic_sar")])
    assert np.isnan(out["p"].iloc[0])
