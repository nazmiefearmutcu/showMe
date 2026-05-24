"""Audit Q3 #7 / #21 — `align_return_series` dropna policy.

The legacy intersection-only join threw away every row where *any*
series had a NaN. For mixed crypto+equity universes (crypto trades 7
days, equity only trading days) this dropped ~70% of rows and tilted
covariance toward crypto.

Pin the three policies and the default (`intersection` for backward
compat).
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from showme.engine.functions.portfolio.return_series import align_return_series


def _mixed_pairs():
    # Equity-style: weekdays only.
    idx_eq = pd.date_range("2024-01-01", periods=20, freq="B")
    eq = pd.Series(np.linspace(0.001, 0.002, 20), index=idx_eq)
    # Crypto-style: all calendar days incl. weekends.
    idx_cr = pd.date_range("2024-01-01", periods=28, freq="D")
    cr = pd.Series(np.linspace(0.005, 0.010, 28), index=idx_cr)
    return [("AAPL", eq), ("BTC", cr)]


def test_default_policy_is_intersection_backward_compat():
    df = align_return_series(_mixed_pairs())
    # All rows must have both columns populated.
    assert df.notna().all().all()
    # Should have ~20 rows (eq trading days that are also in crypto idx).
    assert 15 <= len(df) <= 21


def test_pairwise_policy_keeps_all_calendar_dates():
    df = align_return_series(_mixed_pairs(), policy="pairwise")
    # Pairwise should keep all 28 calendar dates (crypto coverage).
    assert len(df) == 28
    # NaN allowed in equity column on weekends.
    assert df["AAPL"].isna().any()
    # But cov must still work (pandas pairwise).
    cov = df.cov()
    assert cov.shape == (2, 2)
    assert np.isfinite(cov.values).all()


def test_forward_fill_policy_yields_dense_matrix():
    df = align_return_series(_mixed_pairs(), policy="forward_fill")
    # Forward-fill (0) → no NaNs.
    assert not df.isna().any().any()
    # Same row count as pairwise (=28).
    assert len(df) == 28


def test_pairwise_cov_unbiased_vs_intersection_for_mixed_classes():
    """Construct a problem where intersection drops most rows. Compare
    covariance trace; pairwise should reflect the broader data, not the
    handful of co-trading days."""
    rng = np.random.default_rng(7)
    n = 200
    idx_full = pd.date_range("2024-01-01", periods=n, freq="D")
    cr = pd.Series(rng.normal(0.005, 0.05, n), index=idx_full)
    # Equity trades only every 3rd day → ~66 rows.
    idx_eq = idx_full[::3]
    eq = pd.Series(rng.normal(0.001, 0.012, len(idx_eq)), index=idx_eq)
    df_intersection = align_return_series([("EQ", eq), ("CR", cr)])
    df_pairwise = align_return_series([("EQ", eq), ("CR", cr)], policy="pairwise")
    # Intersection collapses to ~66 rows; pairwise keeps ~200.
    assert len(df_intersection) <= 70
    assert len(df_pairwise) >= 195
    # Crypto vol from pairwise should be close to its true std (0.05);
    # intersection-only crypto vol is biased by the 66-row downsample.
    pw_cr_vol = float(df_pairwise["CR"].std())
    assert abs(pw_cr_vol - 0.05) < 0.015
