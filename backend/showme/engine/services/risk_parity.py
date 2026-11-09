"""Risk parity portfolio construction (no SciPy).

Two solvers:
1. **Naive**: weights ∝ 1/σ. Quick approximation when correlations ignored.
2. **Iterative**: Newton-style update on equal risk-contribution objective:
   minimize Σ_i (w_i × MR_i − target)²  where MR_i = (Σ w)_i / sqrt(w' Σ w).

The iterative solver follows Maillard / Roncalli recursions and converges in
a few hundred steps for typical 5–50 asset universes.
"""

from __future__ import annotations

import numpy as np


def naive_inverse_vol(cov: np.ndarray) -> np.ndarray:
    """Weights proportional to 1/σ_i."""
    sigma = np.sqrt(np.diag(cov))
    sigma = np.where(sigma <= 1e-12, 1e-12, sigma)
    inv = 1.0 / sigma
    return inv / inv.sum()


def equal_risk_contribution(
    cov: np.ndarray,
    *,
    target: np.ndarray | None = None,
    tol: float = 1e-9,
    max_iter: int = 5000,
) -> tuple[np.ndarray, dict]:
    """Iterative ERC solver (Spinu 2013 cyclical coordinate descent).

    Each sweep solves every coordinate exactly, so that at the fixed point the
    risk-contribution share of asset i equals ``b_i``. The loop stops only when
    the largest absolute gap between the realized risk shares and ``b`` is
    below ``tol``. ``info["converged"]`` is False when the iteration budget runs
    out, and ``info["residual"]`` is that gap in share units (decimal), so
    callers can flag a non-converged answer.
    """
    n = cov.shape[0]
    if target is None:
        target = np.ones(n) / n
    target = np.asarray(target, dtype=float)
    target = target / target.sum()
    # Spinu (2013) cyclical coordinate descent on the convex problem
    #   min 0.5 x'Sigma x - sum_i b_i log x_i,
    # whose optimum satisfies x_i (Sigma x)_i = b_i. Each coordinate has a
    # closed-form positive root of a_i x^2 + c_i x - b_i = 0 with
    # a_i = Sigma_ii and c_i = sum_{j != i} Sigma_ij x_j. The final weights are
    # x / sum(x), so the risk shares are scale-free.
    diag = np.diag(cov).astype(float)
    x = naive_inverse_vol(cov).astype(float)
    err = float("inf")
    iterations = 0
    for it in range(max_iter):
        iterations = it + 1
        for i in range(n):
            a = max(float(diag[i]), 1e-20)
            c = float(cov[i] @ x - diag[i] * x[i])
            x[i] = (-c + np.sqrt(c * c + 4.0 * a * target[i])) / (2.0 * a)
        w = x / x.sum()
        sw = cov @ w
        port_var = float(w @ sw)
        err = float(np.max(np.abs((w * sw) / max(port_var, 1e-20) - target)))
        if err < tol:
            break
    # Gap for the weights actually returned.
    w = x / x.sum()
    sw = cov @ w
    port_var = float(w @ sw)
    err = float(np.max(np.abs((w * sw) / max(port_var, 1e-20) - target)))
    converged = bool(err < tol)
    return w, {
        "iterations": iterations,
        "residual": err,
        "converged": converged,
        "tolerance": tol,
    }


def risk_contributions(weights: np.ndarray, cov: np.ndarray) -> dict:
    sw = cov @ weights
    port_var = float(weights @ sw)
    port_vol = float(np.sqrt(max(port_var, 1e-20)))
    rc = (weights * sw) / port_vol
    return {
        "portfolio_vol": port_vol,
        "risk_contributions": rc.tolist(),
        "risk_contributions_pct": (rc / port_vol).tolist(),
    }
