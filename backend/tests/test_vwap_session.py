"""Q1 audit HIGH 4: VWAP session anchor (``session_reset`` parameter).

Catalog promises ``session_reset: bool default true``. The compute path
historically ignored the parameter — cumulative since the very first
bar instead of resetting at UTC midnight (crypto convention) or at the
session open hour (equity).

Pins:
  * Default behaviour resets at UTC midnight (each day starts fresh).
  * ``session_reset=False`` keeps the legacy anchored-VWAP (single
    cumulative window from bar 0).
  * Non-DatetimeIndex falls back to single-anchor (no crash).
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from showme.strategies.compute import compute
from showme.strategies.spec import IndicatorRef


def _multi_day_fixture() -> pd.DataFrame:
    """3 days × 24 hourly bars."""
    n = 72
    rng = np.random.default_rng(2026)
    close = 100 + np.cumsum(rng.normal(0, 0.5, n))
    return pd.DataFrame({
        "open": close, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": [1000.0] * n,
    }, index=pd.date_range("2026-01-01 00:00", periods=n, freq="h", tz="UTC"))


def test_vwap_default_resets_at_utc_midnight():
    """First bar of day 2 must reset — VWAP at 00:00 of day 2 should equal
    that bar's typical_price (the cumulative anchor is fresh)."""
    df = _multi_day_fixture()
    out = compute(df, [IndicatorRef(alias="v", id="vwap")])
    # Find first bar of day 2 (index 24 — UTC midnight 2026-01-02).
    day2_idx = pd.Timestamp("2026-01-02 00:00", tz="UTC")
    tp_day2 = (df.loc[day2_idx, "high"] + df.loc[day2_idx, "low"] + df.loc[day2_idx, "close"]) / 3.0
    assert out["v"].loc[day2_idx] == pytest.approx(tp_day2, rel=1e-9)


def test_vwap_session_reset_false_anchored_behaviour():
    """When the caller explicitly disables session reset, VWAP must be
    cumulative since the very first bar (legacy anchored-VWAP)."""
    df = _multi_day_fixture()
    out = compute(df, [
        IndicatorRef(alias="v", id="vwap", params={"session_reset": False}),
    ])
    # Reproduce by hand: cumulative tp*vol / cumulative vol from bar 0.
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    expected = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
    pd.testing.assert_series_equal(
        out["v"].rename("x"), expected.rename("x"),
    )


def test_vwap_session_reset_default_differs_from_no_reset():
    """Default (reset) and no-reset must produce different series on a
    multi-day fixture. Otherwise the parameter is being ignored."""
    df = _multi_day_fixture()
    with_reset = compute(df, [IndicatorRef(alias="v", id="vwap")])
    without_reset = compute(df, [
        IndicatorRef(alias="v", id="vwap", params={"session_reset": False}),
    ])
    # Beyond the first day, the two should diverge.
    day2_onward = with_reset["v"].iloc[24:]
    no_reset_onward = without_reset["v"].iloc[24:]
    assert not day2_onward.equals(no_reset_onward)


def test_vwap_non_datetime_index_falls_back_to_anchored():
    """Synthetic test fixtures sometimes pass a RangeIndex; the function
    must not crash and must produce the legacy anchored-VWAP."""
    n = 30
    close = 100 + np.arange(n, dtype=float)
    df = pd.DataFrame({
        "open": close, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": [1000.0] * n,
    })  # default RangeIndex
    out = compute(df, [IndicatorRef(alias="v", id="vwap")])
    # No crash, valid floats from bar 1 onwards.
    assert not out["v"].iloc[1:].isna().any()
    # Equivalent to anchored-VWAP since the fallback degrades gracefully.
    tp = (df["high"] + df["low"] + df["close"]) / 3.0
    expected = (tp * df["volume"]).cumsum() / df["volume"].cumsum()
    pd.testing.assert_series_equal(
        out["v"].rename("x"), expected.rename("x"),
    )


def test_vwap_session_open_utc_hour_offset():
    """Equity-style sessions can pass e.g. ``session_open_utc_hour=13.5``
    (≈ NYSE open). Bars at 13:30 UTC on consecutive days must be the
    first bar of a session — VWAP equals their typical price."""
    # 4 days × 24h.
    n = 96
    close = 100 + np.arange(n, dtype=float) * 0.1
    df = pd.DataFrame({
        "open": close, "high": close + 1.0, "low": close - 1.0,
        "close": close, "volume": [1000.0] * n,
    }, index=pd.date_range("2026-01-01 00:00", periods=n, freq="h", tz="UTC"))
    out = compute(df, [
        IndicatorRef(alias="v", id="vwap",
                     params={"session_open_utc_hour": 13.0}),
    ])
    # Bars at 13:00 UTC start a new session under the 13.0 offset.
    # ``13:00 UTC on 2026-01-02`` should be a session-start (VWAP = its TP).
    target = pd.Timestamp("2026-01-02 13:00", tz="UTC")
    tp = (df.loc[target, "high"] + df.loc[target, "low"] + df.loc[target, "close"]) / 3.0
    assert out["v"].loc[target] == pytest.approx(tp, rel=1e-9)
