"""Audit Q3 #1 + #2 — Black-Litterman posterior formula + weight renorm.

The legacy `posterior()` returned `cov + τΣ − τΣ Pᵀ M⁻¹ P τΣ` which is
neither the He-Litterman posterior MEAN cov (`τΣ − …`) nor the
posterior RETURN cov (`Σ + (τΣ − …)`). Fix introduces
`posterior_mean_cov()` and `posterior_return_cov()` with explicit
docstring references and keeps the legacy `posterior()` wrapping the
return-cov convention so historical callers don't break.

Also pins the weight-renorm fix (#2): negative `w.sum()` no longer
sign-flips every weight.
"""
from __future__ import annotations

import numpy as np
import pytest

from showme.engine.services.black_litterman import (
    implied_optimal_weights,
    posterior,
    posterior_mean_cov,
    posterior_return_cov,
)


def _toy_cov(n: int = 3) -> np.ndarray:
    rng = np.random.default_rng(7)
    a = rng.normal(size=(n, n))
    cov = a @ a.T / n + 0.05 * np.eye(n)
    return cov


def test_posterior_mean_cov_matches_he_litterman_no_views():
    """Without views, posterior mean COV collapses to τΣ exactly."""
    cov = _toy_cov(3)
    w_mkt = np.array([0.5, 0.3, 0.2])
    tau = 0.05
    pi_bl, sigma_mean = posterior_mean_cov(cov, w_mkt, tau=tau)
    # mean cov = τΣ
    assert np.allclose(sigma_mean, tau * cov, atol=1e-10)
    # mean = π = δΣw_mkt
    assert np.allclose(pi_bl, 2.5 * cov @ w_mkt, atol=1e-10)


def test_posterior_return_cov_no_views_equals_sigma_plus_tau_sigma():
    """Return-cov convention: Σ + τΣ when no views."""
    cov = _toy_cov(3)
    w_mkt = np.array([0.4, 0.4, 0.2])
    tau = 0.05
    _, sigma_ret = posterior_return_cov(cov, w_mkt, tau=tau)
    assert np.allclose(sigma_ret, cov * (1 + tau), atol=1e-10)


def test_posterior_with_views_reduces_mean_uncertainty():
    """Adding a view about asset 0 must SHRINK posterior mean variance.

    Direct check of the He-Litterman formula: Σ_mean_BL = τΣ − τΣ Pᵀ M⁻¹ P τΣ.
    The second (subtracted) term is positive semi-definite, so trace of
    Σ_mean_BL ≤ trace of τΣ.
    """
    cov = _toy_cov(3)
    w_mkt = np.array([0.4, 0.4, 0.2])
    tau = 0.05
    _, sigma_no_view = posterior_mean_cov(cov, w_mkt, tau=tau)
    P = np.array([[1.0, 0.0, 0.0]])
    Q = np.array([0.08])
    _, sigma_with_view = posterior_mean_cov(cov, w_mkt, P=P, Q=Q, tau=tau)
    assert np.trace(sigma_with_view) < np.trace(sigma_no_view)


def test_legacy_posterior_uses_return_convention_by_default():
    """`posterior()` without `convention=` returns return-cov (legacy
    BLAK caller depends on this for MVO)."""
    cov = _toy_cov(3)
    w_mkt = np.array([0.4, 0.4, 0.2])
    tau = 0.05
    _, sigma_default = posterior(cov, w_mkt, tau=tau)
    _, sigma_ret = posterior_return_cov(cov, w_mkt, tau=tau)
    assert np.allclose(sigma_default, sigma_ret, atol=1e-12)


def test_legacy_posterior_no_views_NOT_double_counts_cov():
    """Audit Q3 #1 regression — the old `return pi, tau_sigma + cov` no-view
    branch double-counted Σ if the caller used the default convention. The
    new behavior is Σ + τΣ = (1+τ)Σ, NOT 2Σ + τΣ."""
    cov = _toy_cov(3)
    w_mkt = np.array([0.4, 0.4, 0.2])
    tau = 0.05
    _, sigma = posterior(cov, w_mkt, tau=tau)
    # Defensive: must equal (1+τ)Σ.
    assert np.allclose(sigma, (1 + tau) * cov, atol=1e-10)
    # And must NOT equal the buggy `2cov + tau*cov`.
    assert not np.allclose(sigma, (2 + tau) * cov, atol=1e-3)


def test_implied_optimal_weights_long_only_clips_negatives():
    """Audit Q3 #2 — long-only mode: clip-then-renorm, never sign-flip."""
    # Choose μ such that closed-form `Σ⁻¹μ` yields a negative coordinate.
    cov = np.array([[0.04, 0.01, 0.005],
                    [0.01, 0.09, 0.02],
                    [0.005, 0.02, 0.16]])
    # Force asset 2 to want a negative weight by making its excess return
    # very small AND its cov with asset 1 strong.
    mu = np.array([0.12, 0.10, -0.06])
    w = implied_optimal_weights(mu, cov, delta=1.0, long_only=True)
    assert np.all(w >= 0.0)
    assert pytest.approx(w.sum(), abs=1e-9) == 1.0


def test_implied_optimal_weights_long_short_uses_gross_normalization():
    """Audit Q3 #2 — long-short mode: renorm by |w|.sum() (gross), so a
    net-short book stays oriented; sign flips don't propagate."""
    cov = np.array([[0.04, 0.0], [0.0, 0.04]])
    mu = np.array([0.10, -0.05])
    w = implied_optimal_weights(mu, cov, delta=1.0, long_only=False)
    # Sum of abs values = 1; preserve signs.
    assert pytest.approx(float(np.abs(w).sum()), abs=1e-9) == 1.0
    assert w[0] > 0
    assert w[1] < 0


def test_posterior_invalid_convention_raises():
    cov = _toy_cov(2)
    w_mkt = np.array([0.5, 0.5])
    with pytest.raises(ValueError):
        posterior(cov, w_mkt, convention="weird")
