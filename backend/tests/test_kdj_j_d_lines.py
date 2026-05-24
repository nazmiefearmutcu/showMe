"""Q1 audit: KDJ J line, D line, recursive Chinese formula.

The old ``_compute_kdj`` returned only the EMA of raw stochastic %K
under one name (``kdj_k``). The catalog promises three lines: K, D, J.

Standard Chinese KDJ (TA-Lib / TradingView):
    RSV   = (close - LL) / (HH - LL) * 100
    K[t]  = (1 - 1/m) * K[t-1] + (1/m) * RSV[t]
    D[t]  = (1 - 1/m) * D[t-1] + (1/m) * K[t]
    J[t]  = 3*K[t] - 2*D[t]
Seed: first valid K/D = 50.0 (TA-Lib convention).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


@pytest.fixture
def df() -> pd.DataFrame:
    """60-bar OHLCV fixture."""
    rng = np.random.default_rng(seed=7)
    n = 60
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    open_ = close + rng.normal(0, 0.3, n)
    volume = (1000 + rng.normal(0, 100, n)).clip(min=1)
    idx = pd.date_range("2026-01-01", periods=n, freq="h")
    return pd.DataFrame({"open": open_, "high": high, "low": low,
                         "close": close, "volume": volume}, index=idx)


def test_kdj_d_is_recursive_smoothed_k(df):
    """D[t] = (1 - 1/m) * D[t-1] + (1/m) * K[t]."""
    out = compute(df, [
        IndicatorRef(alias="kdj", id="kdj",
                     params={"period": 9, "m": 3}),
    ])
    k = out["kdj"]
    d = out["kdj_d"]
    valid_mask = ~(k.isna() | d.isna())
    valid_idx = list(valid_mask[valid_mask].index)
    assert len(valid_idx) >= 5, "expected several valid bars"
    alpha = 1.0 / 3.0
    # Verify recursion bar-by-bar after seed.
    for i in range(1, len(valid_idx)):
        prev_ts, ts = valid_idx[i - 1], valid_idx[i]
        if pd.isna(d.loc[prev_ts]) or pd.isna(k.loc[ts]):
            continue
        expected_d = (1.0 - alpha) * d.loc[prev_ts] + alpha * k.loc[ts]
        assert d.loc[ts] == pytest.approx(expected_d, abs=1e-9), (
            f"D recursion broken at {ts}: got {d.loc[ts]}, expected {expected_d}"
        )


def test_kdj_j_equals_3k_minus_2d(df):
    """J = 3K - 2D — identity, must hold on every valid bar."""
    out = compute(df, [IndicatorRef(alias="kdj", id="kdj")])
    valid = ~(out["kdj"].isna() | out["kdj_d"].isna() | out["kdj_j"].isna())
    expected_j = 3 * out["kdj"][valid] - 2 * out["kdj_d"][valid]
    pd.testing.assert_series_equal(
        out["kdj_j"][valid].rename("j"), expected_j.rename("j"),
    )


def test_kdj_k_seeded_at_50(df):
    """First non-NaN K must be exactly 50.0 (TA-Lib convention)."""
    out = compute(df, [IndicatorRef(alias="kdj", id="kdj", params={"period": 9})])
    first_valid = out["kdj"].dropna().iloc[0]
    assert first_valid == pytest.approx(50.0)
    first_valid_d = out["kdj_d"].dropna().iloc[0]
    assert first_valid_d == pytest.approx(50.0)


def test_kdj_first_bars_nan_during_period_warmup():
    """The first ``period-1`` bars have insufficient data for the rolling
    HH/LL → RSV is NaN → K/D/J are NaN."""
    n = 20
    rng = np.random.default_rng(1)
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    df = pd.DataFrame({
        "open": close, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": [1000] * n,
    }, index=pd.date_range("2026-01-01", periods=n, freq="h"))
    out = compute(df, [IndicatorRef(alias="kdj", id="kdj", params={"period": 9})])
    # First 8 bars have insufficient lookback for a 9-bar HH/LL window.
    assert out["kdj"].iloc[:8].isna().all()
    # First valid bar is the 9th (index 8) — seeded at 50.0.
    assert out["kdj"].iloc[8] == pytest.approx(50.0)


def test_kdj_j_can_go_negative_and_above_100():
    """J = 3K - 2D ranges roughly -50 to +150; pin that it can exceed
    [0, 100] (otherwise the indicator is mis-implemented)."""
    # A sharp swing fixture that pushes K to both extremes.
    n = 60
    close = np.concatenate([
        np.linspace(100, 200, 30),   # straight up — K → 100
        np.linspace(200, 100, 30),   # straight down — K → 0
    ])
    df = pd.DataFrame({
        "open": close, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": [1000] * n,
    }, index=pd.date_range("2026-01-01", periods=n, freq="h"))
    out = compute(df, [IndicatorRef(alias="kdj", id="kdj")])
    j = out["kdj_j"].dropna()
    # J should go above 100 during the rally and below 0 during the dump.
    assert j.max() > 95, f"J max={j.max()} — expected >95 on monotone rally"
    assert j.min() < 5, f"J min={j.min()} — expected <5 on monotone selloff"
