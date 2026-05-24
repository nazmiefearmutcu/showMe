"""Q1 audit CRITICAL 1 (Bollinger ddof drift) — engine ↔ compute parity.

``bollinger.py`` engine path uses ``Series.rolling.std()`` (default
``ddof=1``, sample std). ``compute.py`` historically used ``ddof=0``
(population std). The two paths therefore returned *different* bands
for the same period/std_dev pair — rules that referenced ``bbu``/``bbl``
emitted false positives when computed via compute and false negatives
via engine (or vice versa, depending on which path the caller hit).

Pins both paths to sample std (Bollinger 1980 convention).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.engine.indicators.bollinger import BollingerBandsIndicator
from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


@pytest.fixture
def df() -> pd.DataFrame:
    rng = np.random.default_rng(seed=42)
    n = 80
    close = 100 + np.cumsum(rng.normal(0, 1, n))
    high = close + np.abs(rng.normal(0, 0.5, n))
    low = close - np.abs(rng.normal(0, 0.5, n))
    volume = (1000 + rng.normal(0, 100, n)).clip(min=1)
    return pd.DataFrame({
        "open": close, "high": high, "low": low,
        "close": close, "volume": volume,
    }, index=pd.date_range("2026-01-01", periods=n, freq="h"))


def test_compute_bollinger_uses_sample_std(df):
    """compute path: BBU = SMA + k * std(ddof=1)."""
    period, num_std = 20, 2.0
    out = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": period, "num_std": num_std}),
        IndicatorRef(alias="bbl", id="bollinger_lower",
                     params={"period": period, "num_std": num_std}),
    ])
    sma = df["close"].rolling(period).mean()
    sample_std = df["close"].rolling(period).std(ddof=1)
    expected_upper = sma + num_std * sample_std
    expected_lower = sma - num_std * sample_std
    pd.testing.assert_series_equal(
        out["bbu"].dropna().rename("x"), expected_upper.dropna().rename("x"),
    )
    pd.testing.assert_series_equal(
        out["bbl"].dropna().rename("x"), expected_lower.dropna().rename("x"),
    )


def test_engine_and_compute_agree_on_bollinger_bands(df):
    """Both code paths must report identical bands at the last bar."""
    period, num_std = 20, 2.0
    out = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": period, "num_std": num_std}),
        IndicatorRef(alias="bbl", id="bollinger_lower",
                     params={"period": period, "num_std": num_std}),
    ])
    engine = BollingerBandsIndicator(config={
        "indicator_thresholds": {
            "bollinger": {"period": period, "std_dev": num_std,
                          # tame extra knobs so they don't influence raw values:
                          "adx_period": 14, "adx_trend_floor": 20,
                          "high_volume_multiplier": 1.5,
                          "squeeze_threshold": 0.02},
        },
    })
    result = engine.calculate(df)
    raw = result.raw_values or {}
    # Compute's last-bar BBU/BBL must match engine's reported upper/lower.
    assert out["bbu"].iloc[-1] == pytest.approx(raw["upper"], rel=1e-6)
    assert out["bbl"].iloc[-1] == pytest.approx(raw["lower"], rel=1e-6)
    assert out["bbu"].dropna().iloc[-1] != pytest.approx(
        df["close"].rolling(period).mean().iloc[-1]
        + num_std * df["close"].rolling(period).std(ddof=0).iloc[-1],
        rel=1e-6,
    ), "compute path must NOT match ddof=0 (population std) — that was the bug"


def test_population_std_no_longer_matches_compute(df):
    """Regression guard: if anyone reverts compute to ddof=0, this fails."""
    period, num_std = 20, 2.0
    out = compute(df, [
        IndicatorRef(alias="bbu", id="bollinger_upper",
                     params={"period": period, "num_std": num_std}),
    ])
    pop_upper = (df["close"].rolling(period).mean()
                 + num_std * df["close"].rolling(period).std(ddof=0))
    # Should NOT be equal — they differ by sqrt(n / (n-1)) factor.
    assert not out["bbu"].dropna().equals(pop_upper.dropna())
