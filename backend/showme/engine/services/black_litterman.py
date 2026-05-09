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
- Σ_BL — posterior covariance
- w_opt — implied portfolio weights from posterior

Reference: Black & Litterman (1990) + Idzorek (2005) for ω formulation.
"""

from __future__ import annotations

import numpy as np


def implied_returns(cov: np.ndarray, w_mkt: np.ndarray, delta: float = 2.5) -> np.ndarray:
    """Reverse-optimize: π = δ × Σ × w_mkt."""
    return delta * cov @ w_mkt


def posterior(
    cov: np.ndarray,
    w_mkt: np.ndarray,
    P: np.ndarray | None = None,
    Q: np.ndarray | None = None,
    *,
    omega: np.ndarray | None = None,
    delta: float = 2.5,
    tau: float = 0.05,
) -> tuple[np.ndarray, np.ndarray]:
    """Posterior mean & covariance under Black-Litterman."""
    cov.shape[0]
    pi = implied_returns(cov, w_mkt, delta=delta)
    tau_sigma = tau * cov
    if P is None or Q is None or P.size == 0:
        return pi, tau_sigma + cov
    P = np.atleast_2d(P).astype(float)
    Q = np.asarray(Q, dtype=float).reshape(-1)
    if omega is None:
        # Idzorek-lite: diag(P × τΣ × P')
        omega = np.diag(np.diag(P @ tau_sigma @ P.T))
    omega = np.atleast_2d(omega).astype(float)
    # Posterior mean: π_BL = π + τΣ P' (P τΣ P' + Ω)^-1 (Q − Pπ)
    middle = P @ tau_sigma @ P.T + omega
    inv_middle = np.linalg.pinv(middle)
    diff = Q - P @ pi
    pi_bl = pi + tau_sigma @ P.T @ inv_middle @ diff
    # Posterior covariance: Σ_BL = Σ + τΣ - τΣ P' (P τΣ P' + Ω)^-1 P τΣ
    sigma_bl = cov + tau_sigma - tau_sigma @ P.T @ inv_middle @ P @ tau_sigma
    return pi_bl, sigma_bl


def implied_optimal_weights(
    pi_bl: np.ndarray, sigma_bl: np.ndarray, delta: float = 2.5
) -> np.ndarray:
    """w* = (δ Σ)^-1 π — analytical max-utility weights."""
    inv = np.linalg.pinv(delta * sigma_bl)
    w = inv @ pi_bl
    # Renormalize to sum to 1 (long-only friendly)
    s = w.sum()
    return (w / s) if s != 0 else w
