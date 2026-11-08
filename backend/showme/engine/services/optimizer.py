"""Markowitz mean-variance optimization (no SciPy required).

Public API:
    efficient_frontier(returns_df, points=40, allow_short=False, risk_free=0.0)
    max_sharpe(returns_df, risk_free=0.0, allow_short=False)
    min_volatility(returns_df, allow_short=False)
    risk_parity(returns_df)

returns_df is a wide DataFrame (rows = dates, cols = symbols) of
*periodic* returns (e.g. daily). Annualization assumes 252 trading days.

Audit Q3 fixes:
  * #3 — long-only PGD gradient SIGN: minimizing utility
    U(w) = w'Σw − λ μᵀw means gradient is `2Σw − λμ`. The legacy form
    subtracted `2·penalty·μ` from `grad_var`, which moves AWAY from
    high-μ assets when the return constraint is binding. Now we use a
    proper Lagrangian update where λ ≥ 0 is increased while the target
    return is undershot.

  * #4 — `max_sharpe` no longer relies on a 2000-sample Dirichlet search
    for the long-only case. We start from the analytical tangency
    portfolio `w ∝ Σ⁻¹(μ − rf)`, clip negatives, renorm, then run a
    short PGD refinement maximizing Sharpe surrogate.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


_ANN = 252


@dataclass
class PortfolioResult:
    weights: dict[str, float]
    expected_return: float        # annualized
    volatility: float             # annualized
    sharpe: float
    samples: int
    # Solver diagnostics. Only the risk-parity solver sets these; other modes
    # leave them None.
    converged: bool | None = None
    max_rc_error: float | None = None   # max_i |RC_i - 1/n| (share of total risk)


def _annualize(mu: np.ndarray, cov: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    return mu * _ANN, cov * _ANN


def _normalize(w: np.ndarray, allow_short: bool = False) -> np.ndarray:
    if not allow_short:
        w = np.clip(w, 0, None)
    s = w.sum()
    return w / s if s > 0 else np.full_like(w, 1.0 / max(len(w), 1))


def _stats(w: np.ndarray, mu: np.ndarray, cov: np.ndarray, rf: float) -> tuple[float, float, float]:
    ret = float(w @ mu)
    var = float(w @ cov @ w)
    vol = float(np.sqrt(max(var, 1e-12)))
    sharpe = (ret - rf) / vol if vol > 0 else 0.0
    return ret, vol, sharpe


def _project_simplex(w: np.ndarray) -> np.ndarray:
    """Project onto the long-only unit simplex (Wang & Carreira-Perpiñán 2013)."""
    n = len(w)
    if n == 0:
        return w
    u = np.sort(w)[::-1]
    cssv = np.cumsum(u) - 1.0
    ind = np.arange(1, n + 1)
    cond = u - cssv / ind > 0
    rho = int(np.sum(cond))
    if rho == 0:
        return np.full(n, 1.0 / n)
    theta = cssv[rho - 1] / rho
    return np.maximum(w - theta, 0.0)


def _solve_long_only(
    mu: np.ndarray,
    cov: np.ndarray,
    target_return: float | None = None,
    iters: int = 4000,
    lr: float = 0.05,
    seed: int = 0,
) -> np.ndarray:
    """Projected gradient descent on simplex (long-only).

    Objective: minimize w'Σw subject to:
        * sum(w) = 1, w ≥ 0  (simplex)
        * w @ mu ≥ target_return (only if target_return given)

    The constraint is enforced via an adaptive Lagrange multiplier λ ≥ 0
    that grows while the constraint is violated (subgradient ascent on the
    dual). Sign convention:
        L(w, λ) = w'Σw − λ (w @ mu − target)
        ∂L/∂w   = 2 Σ w − λ μ
    so a gradient *descent* step subtracts `2Σw − λμ` from w.
    """
    n = len(mu)
    rng = np.random.default_rng(seed)
    w = rng.dirichlet(np.ones(n))
    lam = 0.0
    for _ in range(iters):
        grad_var = 2.0 * cov @ w
        if target_return is None:
            grad = grad_var - 0.0001 * mu
        else:
            grad = grad_var - lam * mu
        w = w - lr * grad
        w = _project_simplex(w)
        if target_return is not None:
            shortfall = target_return - float(w @ mu)
            # Adaptive dual: bump λ up while undershooting, decay otherwise.
            if shortfall > 0:
                lam = lam + lr * shortfall * 50.0
            else:
                lam = max(0.0, lam * 0.999)
    return w


def _solve_unconstrained(mu: np.ndarray, cov: np.ndarray,
                         target_return: float) -> np.ndarray:
    """Closed-form Markowitz with cov^-1; allows shorts."""
    inv = np.linalg.pinv(cov)
    ones = np.ones(len(mu))
    A = float(ones @ inv @ ones)
    B = float(ones @ inv @ mu)
    C = float(mu @ inv @ mu)
    D = A * C - B * B
    if abs(D) < 1e-12:
        return _normalize(np.ones(len(mu)) / len(mu))
    lam = (C - B * target_return) / D
    gam = (A * target_return - B) / D
    w = lam * (inv @ ones) + gam * (inv @ mu)
    return w


def min_volatility(returns: pd.DataFrame, *, allow_short: bool = False,
                   risk_free: float = 0.0) -> PortfolioResult:
    mu = returns.mean().values
    cov = returns.cov().values
    mu_a, cov_a = _annualize(mu, cov)
    if allow_short:
        inv = np.linalg.pinv(cov_a)
        ones = np.ones(len(mu_a))
        w = inv @ ones / float(ones @ inv @ ones)
    else:
        w = _solve_long_only(np.zeros_like(mu_a), cov_a)
    ret, vol, sh = _stats(w, mu_a, cov_a, risk_free)
    return PortfolioResult(
        weights={c: float(wi) for c, wi in zip(returns.columns, w)},
        expected_return=ret, volatility=vol, sharpe=sh, samples=int(len(returns)),
    )


def _max_sharpe_long_only_refine(
    mu_a: np.ndarray,
    cov_a: np.ndarray,
    rf: float,
    w0: np.ndarray,
    iters: int = 1500,
    lr: float = 0.02,
) -> np.ndarray:
    """Long-only Sharpe-maximizing refinement via projected gradient *ascent*.

    Sharpe(w) = (w·μ − rf) / sqrt(w'Σw)
    ∇Sharpe   = (μ·σ − (w·μ − rf)·(Σw/σ)) / σ²    (chain rule)
    where σ = sqrt(w'Σw).
    """
    w = _project_simplex(w0)
    for _ in range(iters):
        excess = float(w @ mu_a) - rf
        var = float(w @ cov_a @ w)
        vol = np.sqrt(max(var, 1e-12))
        if vol <= 0:
            break
        grad = (mu_a * vol - excess * (cov_a @ w) / vol) / max(var, 1e-12)
        w = _project_simplex(w + lr * grad)
    return w


def max_sharpe(returns: pd.DataFrame, *, risk_free: float = 0.0,
                allow_short: bool = False) -> PortfolioResult:
    mu = returns.mean().values
    cov = returns.cov().values
    mu_a, cov_a = _annualize(mu, cov)
    inv = np.linalg.pinv(cov_a)
    excess = mu_a - risk_free
    w_tan = inv @ excess
    if allow_short:
        s = float(np.sum(w_tan))
        w = w_tan / s if abs(s) > 1e-12 else _normalize(np.ones_like(mu_a), allow_short=True)
    else:
        # Audit Q3 #4: analytical tangency, clip negatives, renorm, then SLSQP-
        # equivalent projected-gradient ascent on Sharpe.
        w_seed = np.maximum(w_tan, 0.0)
        s = float(w_seed.sum())
        if s > 0:
            w_seed = w_seed / s
        else:
            w_seed = np.full_like(mu_a, 1.0 / max(len(mu_a), 1))
        w = _max_sharpe_long_only_refine(mu_a, cov_a, risk_free, w_seed)
    ret, vol, sh = _stats(w, mu_a, cov_a, risk_free)
    return PortfolioResult(
        weights={c: float(wi) for c, wi in zip(returns.columns, w)},
        expected_return=ret, volatility=vol, sharpe=sh, samples=int(len(returns)),
    )


def efficient_frontier(returns: pd.DataFrame, *, points: int = 40,
                        allow_short: bool = False,
                        risk_free: float = 0.0) -> list[PortfolioResult]:
    mu = returns.mean().values
    cov = returns.cov().values
    mu_a, cov_a = _annualize(mu, cov)
    targets = np.linspace(mu_a.min(), mu_a.max(), points)
    out: list[PortfolioResult] = []
    for t in targets:
        try:
            if allow_short:
                w = _solve_unconstrained(mu_a, cov_a, t)
            else:
                w = _solve_long_only(mu_a, cov_a, target_return=t)
            ret, vol, sh = _stats(w, mu_a, cov_a, risk_free)
            out.append(PortfolioResult(
                weights={c: float(wi) for c, wi in zip(returns.columns, w)},
                expected_return=ret, volatility=vol, sharpe=sh,
                samples=int(len(returns)),
            ))
        except Exception:
            continue
    return out


_ERC_TOL = 1e-9   # max_i |RC_i - 1/n| below this counts as converged


def _erc_weights(cov: np.ndarray, *, max_sweeps: int) -> tuple[np.ndarray, bool, float]:
    """Equal-risk-contribution weights via cyclical coordinate descent.

    ERC is the first-order condition of the convex problem
        min_y  0.5 * y' Σ y  -  Σ_i b_i ln y_i ,     y > 0,  b_i = 1/n
    whose stationarity reads y_i (Σy)_i = b_i. Normalising w = y / sum(y)
    therefore gives RC_i(w) = b_i exactly. Each coordinate has a closed-form
    minimiser: with a_i = Σ_ii and c_i = Σ_{j≠i} Σ_ij y_j,
        a_i y_i^2 + c_i y_i - b_i = 0   =>   y_i = (-c_i + sqrt(c_i^2 + 4 a_i b_i)) / (2 a_i)
    (Spinu 2013). Convergence is verified on the risk contributions
    themselves instead of assumed from an iteration count.

    Returns (weights, converged, max_rc_error) where max_rc_error is
    max_i |RC_i - 1/n| on the normalised weights.
    """
    n = cov.shape[0]
    b = np.full(n, 1.0 / n)
    diag = np.diag(cov).astype(float)
    y = 1.0 / np.sqrt(diag)
    err = float("inf")
    for _ in range(max_sweeps):
        for i in range(n):
            c = float(cov[i] @ y) - diag[i] * y[i]
            y[i] = (-c + np.sqrt(c * c + 4.0 * diag[i] * b[i])) / (2.0 * diag[i])
        w = y / y.sum()
        sw = cov @ w
        var = float(w @ sw)
        rc = w * sw / var
        err = float(np.max(np.abs(rc - b)))
        if err < _ERC_TOL:
            return w, True, err
    return w, False, err


def risk_parity(returns: pd.DataFrame, iters: int = 5000, *,
                risk_free: float = 0.0) -> PortfolioResult:
    """Equal Risk Contribution (ERC) long-only portfolio.

    ``iters`` caps the number of coordinate-descent sweeps. The result reports
    ``converged`` and ``max_rc_error``; callers must surface a non-converged
    result rather than present it as equal-risk.

    Raises ValueError when an asset has no variance (its risk contribution is
    undefined).
    """
    cov = returns.cov().values
    mu = returns.mean().values
    mu_a, cov_a = _annualize(mu, cov)
    n = cov_a.shape[0]
    if n == 0:
        raise ValueError("risk_parity requires at least one asset")
    if not np.all(np.isfinite(cov_a)) or np.any(np.diag(cov_a) <= 0):
        raise ValueError("risk_parity requires finite, positive variance for every asset")
    if n == 1:
        w = np.ones(1)
        converged, err = True, 0.0
    else:
        w, converged, err = _erc_weights(cov_a, max_sweeps=max(1, int(iters)))
    ret, vol, sh = _stats(w, mu_a, cov_a, risk_free)
    return PortfolioResult(
        weights={c: float(wi) for c, wi in zip(returns.columns, w)},
        expected_return=ret, volatility=vol, sharpe=sh, samples=int(len(returns)),
        converged=bool(converged), max_rc_error=float(err),
    )
