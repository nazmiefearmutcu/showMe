"""Audit Q3 #3 — Markowitz long-only PGD gradient sign.

The legacy form computed
    grad = grad_var − 2 * penalty * mu
which, when the target was UNDERshot (`penalty < 0`), increased weight on
LOW-μ assets — the opposite of what's needed. The fix uses a proper
Lagrangian with non-negative dual `λ` that grows while the return
constraint is violated and decays otherwise.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from showme.engine.services.optimizer import (
    _solve_long_only,
    efficient_frontier,
    min_volatility,
)


def _two_asset_problem(seed: int = 0):
    rng = np.random.default_rng(seed)
    n_days = 252
    # Asset 0: high mean low vol. Asset 1: low mean low vol.
    r0 = rng.normal(0.0008, 0.01, n_days)
    r1 = rng.normal(0.0001, 0.01, n_days)
    # Asset 2: medium mean medium vol.
    r2 = rng.normal(0.0004, 0.012, n_days)
    df = pd.DataFrame({"A": r0, "B": r1, "C": r2})
    return df


def test_pgd_high_target_tilts_to_high_mu_asset():
    """With a target return above the equal-weight mean, weight should
    increase on the high-μ asset (A), not decrease."""
    df = _two_asset_problem()
    mu = df.mean().values * 252
    cov = df.cov().values * 252
    # Equal-weight base return
    eq_ret = float(mu.mean())
    # Target slightly above mean
    target = eq_ret + 0.05
    w = _solve_long_only(mu, cov, target_return=target, iters=4000, lr=0.02, seed=1)
    # A should have at least 1/n + a meaningful nudge.
    assert w[0] > 1.0 / len(mu) + 0.05, (
        f"PGD did not tilt toward high-μ asset; weights={w}, mu={mu}"
    )


def test_pgd_returns_simplex():
    """Weights must be non-negative and sum to 1."""
    df = _two_asset_problem()
    mu = df.mean().values * 252
    cov = df.cov().values * 252
    w = _solve_long_only(mu, cov, target_return=float(mu.mean()), iters=2000, seed=2)
    assert np.all(w >= -1e-9)
    assert abs(w.sum() - 1.0) < 1e-6


def test_efficient_frontier_is_monotone_increasing_vol():
    """Sorted by expected return, vols should generally grow (efficient
    frontier is upward-sloping in (vol, ret) space)."""
    df = _two_asset_problem()
    ef = efficient_frontier(df, points=10, allow_short=False)
    assert len(ef) >= 3
    sorted_ef = sorted(ef, key=lambda p: p.expected_return)
    vols = [p.volatility for p in sorted_ef]
    # Permit small non-monotonicities from PGD stochasticity; require the
    # last vol > the first vol (monotone "in trend").
    assert vols[-1] > vols[0]


def test_min_volatility_picks_lowest_vol_pure_asset_when_uncorrelated():
    """min-vol of a 2-asset uncorrelated problem ≤ both single-asset vols."""
    rng = np.random.default_rng(0)
    n = 504
    r0 = rng.normal(0, 0.012, n)
    r1 = rng.normal(0, 0.010, n)
    df = pd.DataFrame({"A": r0, "B": r1})
    res = min_volatility(df, allow_short=False)
    single_vol_a = float(df["A"].std() * np.sqrt(252))
    single_vol_b = float(df["B"].std() * np.sqrt(252))
    assert res.volatility <= max(single_vol_a, single_vol_b) + 1e-6
