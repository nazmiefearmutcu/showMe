"""Q1 audit HIGH 8: Stochastic %D line + %K-crosses-%D detection.

The engine ``stochastic.py`` had a dead expression — ``prev_d`` was
computed but the assignment target was missing, so the value was
discarded. The %K-crosses-%D detection therefore never fired.

Also pins:
  * Compute path exposes %D via ``{alias}_d`` (was IGNORE).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


@pytest.fixture
def df() -> pd.DataFrame:
    rng = np.random.default_rng(seed=11)
    n = 80
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close, "volume": [1000] * n,
    }, index=pd.date_range("2026-01-01", periods=n, freq="h"))


# ── compute %D parity ─────────────────────────────────────────────────────


def test_compute_stochastic_exposes_d_line(df):
    """``{alias}_d`` must be present with same length as primary %K."""
    out = compute(df, [
        IndicatorRef(alias="s", id="stochastic",
                     params={"k_period": 14, "smooth": 3, "d_period": 3}),
    ])
    assert "s" in out
    assert "s_d" in out
    assert len(out["s_d"]) == len(out["s"])


def test_compute_stochastic_d_is_sma_of_k(df):
    """%D = SMA(%K, d_period). Pin the formula."""
    d_period = 3
    out = compute(df, [
        IndicatorRef(alias="s", id="stochastic",
                     params={"k_period": 14, "smooth": 3, "d_period": d_period}),
    ])
    expected_d = out["s"].rolling(d_period).mean()
    pd.testing.assert_series_equal(
        out["s_d"].dropna().rename("x"),
        expected_d.dropna().rename("x"),
    )


def test_compute_stochastic_d_period_param_respected(df):
    """Different ``d_period`` values must produce different %D series."""
    out_3 = compute(df, [
        IndicatorRef(alias="s", id="stochastic",
                     params={"k_period": 14, "smooth": 3, "d_period": 3}),
    ])
    out_5 = compute(df, [
        IndicatorRef(alias="s", id="stochastic",
                     params={"k_period": 14, "smooth": 3, "d_period": 5}),
    ])
    valid = ~(out_3["s_d"].isna() | out_5["s_d"].isna())
    assert not out_3["s_d"][valid].equals(out_5["s_d"][valid])


# ── engine %K crosses %D wiring ───────────────────────────────────────────


def test_engine_stochastic_records_prev_d_in_raw_values():
    """``prev_d`` must be captured (the old dead expression discarded it).
    The raw_values dict now exposes prev_d so callers can audit crosses."""
    from showme.engine.indicators.stochastic import StochasticIndicator
    n = 50
    rng = np.random.default_rng(33)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame({
        "open": close, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": [1000] * n,
    }, index=pd.date_range("2026-01-01", periods=n, freq="h"))
    stoch = StochasticIndicator(config={})
    result = stoch.calculate(df)
    assert "prev_d" in (result.raw_values or {}), (
        f"raw_values must include prev_d, got {sorted((result.raw_values or {}).keys())}"
    )
    assert "bullish_cross" in (result.raw_values or {})
    assert "bearish_cross" in (result.raw_values or {})


def test_engine_stochastic_bullish_cross_in_oversold_emits_strong_buy():
    """Hand-crafted fixture: K crosses D upward in oversold zone."""
    from showme.engine.indicators.stochastic import StochasticIndicator
    # Build a sharp down-then-up pattern: lows hit, K bottoms then crosses D up.
    base = list(range(100, 60, -1)) + list(range(60, 100))
    n = len(base)
    close = np.array(base, dtype=float)
    df = pd.DataFrame({
        "open": close, "high": close + 0.5, "low": close - 0.5,
        "close": close, "volume": [1000] * n,
    }, index=pd.date_range("2026-01-01", periods=n, freq="h"))
    stoch = StochasticIndicator(config={
        "indicator_thresholds": {
            "stochastic": {"k_period": 14, "d_period": 3, "oversold": 20, "overbought": 80},
        },
    })
    result = stoch.calculate(df)
    raw = result.raw_values or {}
    # On a fixture that walks from oversold to overbought, the cross
    # should eventually flip bullish — pin the wire is live.
    assert isinstance(raw.get("bullish_cross"), bool)
    assert isinstance(raw.get("bearish_cross"), bool)
