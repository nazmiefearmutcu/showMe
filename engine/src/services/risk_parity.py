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
    """Iterative ERC solver. Returns (weights, info)."""
    n = cov.shape[0]
    if target is None:
        target = np.ones(n) / n
    target = np.asarray(target, dtype=float)
    target = target / target.sum()
    w = naive_inverse_vol(cov)
    last_err = None
    for it in range(max_iter):
        sw = cov @ w
        port_var = float(w @ sw)
        port_vol = np.sqrt(max(port_var, 1e-20))
        # Risk contributions r_i = w_i × (Σw)_i / σ_p
        rc = (w * sw) / port_vol
        # Target risk = target_i × σ_p
        diff = rc - target * port_vol
        err = float(np.linalg.norm(diff))
        if last_err is not None and abs(last_err - err) < tol:
            break
        last_err = err
        # Cyclical update: w_i ← w_i × (target_i × σ_p) / (Σw)_i
        # but use damping to avoid oscillation.
        update = (target * port_vol) / np.where(np.abs(sw) < 1e-20, 1e-20, sw)
        w = w * (0.5 + 0.5 * update)
        w = np.where(w < 1e-12, 1e-12, w)
        w = w / w.sum()
    return w, {"iterations": it + 1, "residual": err}


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
