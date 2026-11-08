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
    """Iterative ERC solver (cyclical update, Spinu 2013 / Maillard et al.).

    Each step sets ``w_i <- b_i * sigma_p / (Sigma w)_i`` and renormalizes, so
    the risk-contribution share of asset i becomes ``b_i`` at that step. The
    loop stops only when the largest absolute gap between the realized risk
    shares and ``b`` is below ``tol``. ``info["converged"]`` is False when the
    iteration budget runs out, and ``info["residual"]`` is that gap in share
    units (decimal), so callers can flag a non-converged answer.
    """
    n = cov.shape[0]
    if target is None:
        target = np.ones(n) / n
    target = np.asarray(target, dtype=float)
    target = target / target.sum()
    w = naive_inverse_vol(cov)
    err = float("inf")
    iterations = 0
    for it in range(max_iter):
        iterations = it + 1
        sw = cov @ w
        port_var = float(w @ sw)
        port_vol = float(np.sqrt(max(port_var, 1e-20)))
        # Realized risk shares s_i = w_i (Sigma w)_i / sigma_p^2 (sum to 1).
        shares = (w * sw) / max(port_var, 1e-20)
        err = float(np.max(np.abs(shares - target)))
        if err < tol:
            break
        # Cyclical update: w_i <- b_i * sigma_p / (Sigma w)_i, then normalize.
        denom = np.where(np.abs(sw) < 1e-20, 1e-20, sw)
        w = target * port_vol / denom
        w = np.where(w < 1e-12, 1e-12, w)
        w = w / w.sum()
    # Measure the gap for the weights actually returned (the last update may
    # have run after the final check).
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
