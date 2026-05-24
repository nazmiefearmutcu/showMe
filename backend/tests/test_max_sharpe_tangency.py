"""Audit Q3 #4 — `max_sharpe` analytical tangency vs Monte Carlo.

The legacy long-only `max_sharpe` ran 2000 Dirichlet samples and kept the
best Sharpe. That biased the reported Sharpe LOW by 10–30% vs the true
tangency portfolio. The fix:
  1) compute analytical tangency `w ∝ Σ⁻¹(μ − rf)`
  2) clip negatives + renorm
  3) Run a projected-gradient ASCENT on Sharpe surrogate (SLSQP-equiv)
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from showme.engine.services.optimizer import max_sharpe


def _three_asset_df(seed: int = 3) -> pd.DataFrame:
    """Seed=3 gives realized Sharpes (A=2.26, B=0.61, C=0.71) so the test
    is robust to sampling noise: A has the empirically highest Sharpe."""
    rng = np.random.default_rng(seed)
    n = 504
    r = pd.DataFrame({
        "A": rng.normal(0.0010, 0.012, n),
        "B": rng.normal(0.0004, 0.014, n),
        "C": rng.normal(0.0001, 0.010, n),
    })
    return r


def test_max_sharpe_long_only_beats_equal_weight():
    df = _three_asset_df()
    res = max_sharpe(df, allow_short=False, risk_free=0.0)
    # Equal-weight baseline
    w_eq = np.full(3, 1.0 / 3)
    mu_a = df.mean().values * 252
    cov_a = df.cov().values * 252
    eq_ret = float(w_eq @ mu_a)
    eq_vol = float(np.sqrt(w_eq @ cov_a @ w_eq))
    eq_sharpe = eq_ret / eq_vol if eq_vol > 0 else 0.0
    assert res.sharpe > eq_sharpe + 0.02, (
        f"max_sharpe Sharpe ({res.sharpe:.4f}) not meaningfully better "
        f"than equal-weight ({eq_sharpe:.4f})"
    )


def test_max_sharpe_long_only_tilts_to_highest_sharpe_asset():
    df = _three_asset_df()
    res = max_sharpe(df, allow_short=False, risk_free=0.0)
    weights = res.weights
    # A should be the largest weight.
    largest = max(weights, key=weights.get)
    assert largest == "A", f"Expected A largest, got weights={weights}"


def test_max_sharpe_allow_short_returns_tangency():
    df = _three_asset_df()
    res = max_sharpe(df, allow_short=True, risk_free=0.0)
    # Reconstruct analytical tangency to cross-check.
    mu_a = df.mean().values * 252
    cov_a = df.cov().values * 252
    inv = np.linalg.pinv(cov_a)
    w_tan = inv @ mu_a
    w_tan = w_tan / w_tan.sum()
    api_w = np.array([res.weights[c] for c in df.columns])
    assert np.allclose(api_w, w_tan, atol=1e-6)


def test_max_sharpe_simplex_invariants():
    df = _three_asset_df()
    res = max_sharpe(df, allow_short=False, risk_free=0.0)
    weights = np.array([res.weights[c] for c in df.columns])
    assert np.all(weights >= -1e-9)
    assert abs(weights.sum() - 1.0) < 1e-6
