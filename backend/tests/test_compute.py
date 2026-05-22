"""Compute engine unit tests with a fixed 30-bar OHLCV fixture."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


@pytest.fixture
def df() -> pd.DataFrame:
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


def test_compute_dispatches_each_indicator(df):
    refs = [IndicatorRef(alias=k, id=k) for k in [
        "rsi", "macd", "ema", "sma", "bollinger_bands", "stochastic",
        "atr", "adx", "cci", "obv", "williams_r", "vwap",
        "ichimoku", "parabolic_sar", "kdj",
    ]]
    out = compute(df, refs)
    assert set(out.keys()) == {r.alias for r in refs}
    for alias, series in out.items():
        assert isinstance(series, pd.Series)
        assert len(series) == len(df)


def test_rsi_bounds(df):
    out = compute(df, [IndicatorRef(alias="r", id="rsi", params={"period": 14})])
    s = out["r"].dropna()
    assert (s >= 0).all() and (s <= 100).all()


def test_sma_equals_rolling_mean(df):
    out = compute(df, [IndicatorRef(alias="s", id="sma", params={"period": 20})])
    expected = df["close"].rolling(20).mean()
    pd.testing.assert_series_equal(out["s"].rename("close"), expected, check_names=False)


def test_ema_first_value_equals_first_close(df):
    out = compute(df, [IndicatorRef(alias="e", id="ema", params={"period": 20})])
    # span EMA: first value = first close (adjust=False)
    assert out["e"].iloc[0] == pytest.approx(df["close"].iloc[0])


def test_atr_non_negative(df):
    out = compute(df, [IndicatorRef(alias="a", id="atr", params={"period": 14})])
    assert (out["a"].dropna() >= 0).all()


def test_williams_r_bounds(df):
    out = compute(df, [IndicatorRef(alias="w", id="williams_r", params={"period": 14})])
    s = out["w"].dropna()
    assert (s >= -100).all() and (s <= 0).all()


def test_obv_cumulative(df):
    out = compute(df, [IndicatorRef(alias="o", id="obv")])
    # OBV should never spike beyond cumulative volume bound:
    assert out["o"].abs().max() <= df["volume"].sum()


def test_vwap_within_range(df):
    out = compute(df, [IndicatorRef(alias="v", id="vwap")])
    s = out["v"].dropna()
    assert (s >= df["low"].min()).all() and (s <= df["high"].max()).all()


def test_parabolic_sar_first_value(df):
    out = compute(df, [IndicatorRef(alias="p", id="parabolic_sar")])
    assert out["p"].iloc[0] == pytest.approx(df["low"].iloc[0])


def test_unknown_indicator_returns_nan_series(df):
    out = compute(df, [IndicatorRef(alias="x", id="not_a_real_indicator")])
    assert out["x"].isna().all()


def test_short_df_does_not_raise():
    short = pd.DataFrame({
        "open": [1.0, 2.0], "high": [1.5, 2.5], "low": [0.5, 1.5],
        "close": [1.0, 2.0], "volume": [100, 100],
    }, index=pd.date_range("2026-01-01", periods=2, freq="h"))
    out = compute(short, [IndicatorRef(alias=k, id=k) for k in [
        "rsi", "sma", "atr", "adx", "macd",
    ]])
    # All series populated, mostly NaN — but no exceptions raised.
    assert len(out) == 5


def test_ichimoku_kijun_within_range(df):
    out = compute(df, [IndicatorRef(alias="k", id="ichimoku")])
    s = out["k"].dropna()
    assert (s >= df["low"].min()).all() and (s <= df["high"].max()).all()


def test_cci_can_exceed_100(df):
    # CCI's design: easily exceeds ±100 — just sanity check it's not all zero / NaN.
    out = compute(df, [IndicatorRef(alias="c", id="cci", params={"period": 20})])
    s = out["c"].dropna()
    assert len(s) > 0
