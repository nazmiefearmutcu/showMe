"""Black-Litterman expected returns model.

Inputs:
- Σ — covariance matrix (annualized) of asset returns
- w_mkt — market-cap weights (prior)
- δ — risk aversion (default 2.5)
- τ — uncertainty in prior (default 0.05)
- P — pick matrix (k × n) for views
- Q — k-vector of view returns
- Ω — k × k diagonal view-uncertainty (auto-generated if None)

Outputs:
- π_BL — posterior mean returns
- Σ_mean_BL — posterior covariance of the MEAN-return estimator
- Σ_return_BL — posterior covariance of RETURNS (use for portfolio risk)
- w_opt — implied portfolio weights from posterior

Reference: He & Litterman 1999 ("The Intuition Behind Black-Litterman Model
Portfolios", Goldman Sachs Investment Management Research, eq. 8). Also
Idzorek (2005) for the Ω formulation.

KEY FIX (audit Q3 #1): the posterior covariance formula in He-Litterman is
    Σ_mean_BL = τΣ − τΣ Pᵀ (P τΣ Pᵀ + Ω)⁻¹ P τΣ
This is the covariance of the posterior MEAN estimator, not of the returns
themselves. If the caller wants "covariance of returns" they must add Σ:
    Σ_return_BL = Σ + Σ_mean_BL
The legacy `posterior()` mistakenly returned `cov + τΣ − τΣ Pᵀ M⁻¹ P τΣ`,
which is neither convention. Callers should now call `posterior_mean_cov()`
(explicit) or `posterior_return_cov()` (Σ + posterior-mean cov).
"""

from __future__ import annotations

import numpy as np


def implied_returns(cov: np.ndarray, w_mkt: np.ndarray, delta: float = 2.5) -> np.ndarray:
    """Reverse-optimize: π = δ × Σ × w_mkt."""
    return delta * cov @ w_mkt


def _solve_posterior(
    cov: np.ndarray,
    w_mkt: np.ndarray,
    P: np.ndarray | None,
    Q: np.ndarray | None,
    *,
    omega: np.ndarray | None,
    delta: float,
    tau: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Internal: returns (posterior_mean, posterior_mean_covariance).

    Posterior of the MEAN-return estimator (He-Litterman eq. 7-8):
        π_BL    = π + τΣ Pᵀ (P τΣ Pᵀ + Ω)⁻¹ (Q − Pπ)
        Σ_μ_BL = τΣ − τΣ Pᵀ (P τΣ Pᵀ + Ω)⁻¹ P τΣ
    """
    pi = implied_returns(cov, w_mkt, delta=delta)
    tau_sigma = tau * cov
    if P is None or Q is None or P.size == 0:
        # No views → posterior collapses to prior mean π with covariance τΣ
        return pi, tau_sigma
    P = np.atleast_2d(P).astype(float)
    Q = np.asarray(Q, dtype=float).reshape(-1)
    if omega is None:
        # Idzorek-lite: diag(P × τΣ × P')
        omega = np.diag(np.diag(P @ tau_sigma @ P.T))
    omega = np.atleast_2d(omega).astype(float)
    middle = P @ tau_sigma @ P.T + omega
    inv_middle = np.linalg.pinv(middle)
    diff = Q - P @ pi
    pi_bl = pi + tau_sigma @ P.T @ inv_middle @ diff
    sigma_mean_bl = tau_sigma - tau_sigma @ P.T @ inv_middle @ P @ tau_sigma
    return pi_bl, sigma_mean_bl


def posterior_mean_cov(
    cov: np.ndarray,
    w_mkt: np.ndarray,
    P: np.ndarray | None = None,
    Q: np.ndarray | None = None,
    *,
    omega: np.ndarray | None = None,
    delta: float = 2.5,
    tau: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Posterior MEAN + posterior-of-mean COVARIANCE (He-Litterman eq. 7-8).

    Use when you care about the uncertainty of the expected-return estimate
    itself (e.g. confidence-weighted view blending).
    """
    return _solve_posterior(
        cov, w_mkt, P, Q, omega=omega, delta=delta, tau=tau
    )


def posterior_return_cov(
    cov: np.ndarray,
    w_mkt: np.ndarray,
    P: np.ndarray | None = None,
    Q: np.ndarray | None = None,
    *,
    omega: np.ndarray | None = None,
    delta: float = 2.5,
    tau: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Posterior MEAN + RETURN COVARIANCE (Σ + posterior-of-mean cov).

    Use this convention when feeding the result into a mean-variance optimizer
    that expects the covariance of *returns*. This matches the convention used
    by most Black-Litterman implementations in practice and is what the legacy
    `posterior()` *attempted* to return (but with the bug noted in the module
    docstring).
    """
    pi_bl, sigma_mean_bl = _solve_posterior(
        cov, w_mkt, P, Q, omega=omega, delta=delta, tau=tau
    )
    return pi_bl, cov + sigma_mean_bl


def posterior(
    cov: np.ndarray,
    w_mkt: np.ndarray,
    P: np.ndarray | None = None,
    Q: np.ndarray | None = None,
    *,
    omega: np.ndarray | None = None,
    delta: float = 2.5,
    tau: float = 0.05,
    convention: str = "return",
) -> tuple[np.ndarray, np.ndarray]:
    """Posterior mean & covariance under Black-Litterman.

    ``convention`` selects which covariance is returned:
      * ``"return"`` (default): Σ + posterior-mean cov — feed into MVO.
      * ``"mean"``:             posterior-mean cov only (He-Litterman eq. 8).

    The default matches the historical caller contract (BLAK function expects
    a return-cov-like matrix for MVO). The legacy implementation had an
    incorrect extra `cov` term *and* was missing the `cov` addend in the
    no-views branch; both are now fixed.
    """
    if convention not in {"return", "mean"}:
        raise ValueError(f"convention must be 'return' or 'mean', got {convention!r}")
    if convention == "mean":
        return posterior_mean_cov(
            cov, w_mkt, P, Q, omega=omega, delta=delta, tau=tau
        )
    return posterior_return_cov(
        cov, w_mkt, P, Q, omega=omega, delta=delta, tau=tau
    )


def implied_optimal_weights(
    pi_bl: np.ndarray,
    sigma_bl: np.ndarray,
    delta: float = 2.5,
    *,
    long_only: bool = True,
) -> np.ndarray:
    """w* = (δ Σ)^-1 π — analytical max-utility weights.

    Renormalization (audit Q3 #2):
      * ``long_only=True``  → clip negatives to 0, then renorm by sum.
      * ``long_only=False`` → renorm by ``|w|.sum()`` (gross exposure) so a
        net-negative book does not sign-flip every weight.
    """
    inv = np.linalg.pinv(delta * sigma_bl)
    w = inv @ pi_bl
    if long_only:
        w = np.maximum(w, 0.0)
        s = float(w.sum())
        if s > 0:
            return w / s
        # All-zero after clip → fall back to equal weight (defensive)
        n = len(w)
        return np.full(n, 1.0 / max(n, 1))
    gross = float(np.abs(w).sum())
    if gross > 0:
        return w / gross
    n = len(w)
    return np.full(n, 1.0 / max(n, 1))
