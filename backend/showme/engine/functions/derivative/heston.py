"""Heston (1993) stochastic-vol option pricing — Monte Carlo + closed-form FFT.

Plan §12.1 (OVME advanced model). NumPy yeterli; QuantLib opsiyonel.

Used by OVME with `model="heston"` parametresi.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


@dataclass
class HestonParams:
    kappa: float = 2.0     # mean reversion speed
    theta: float = 0.04    # long-run variance
    sigma: float = 0.4     # vol of vol
    rho: float = -0.6      # correlation S↔V
    v0: float = 0.04       # initial variance


def heston_mc(
    S: float, K: float, T: float, r: float, q: float,
    params: HestonParams,
    *,
    is_call: bool = True,
    paths: int = 30_000,
    steps: int = 100,
    antithetic: bool = True,
    seed: int | None = 42,
) -> dict[str, float]:
    """Monte Carlo Heston with full-truncation Euler scheme.

    D03-2026-05-24 (H21): variance update now references the truncated Vp
    in BOTH the drift and diffusion terms; old code used raw ``Vt`` in
    the drift so Vt could go negative even though Vp was clamped. This
    is the standard Andersen 2008 "Full Truncation" recipe.
    """
    if seed is not None:
        rng = np.random.default_rng(seed)
    else:
        rng = np.random.default_rng()
    dt = T / steps
    n = paths if not antithetic else paths // 2
    Z1 = rng.standard_normal((steps, n))
    Z2 = params.rho * Z1 + math.sqrt(1 - params.rho ** 2) * rng.standard_normal((steps, n))
    if antithetic:
        Z1 = np.concatenate([Z1, -Z1], axis=1)
        Z2 = np.concatenate([Z2, -Z2], axis=1)
    St = np.full(Z1.shape[1], S, dtype=float)
    Vt = np.full(Z1.shape[1], params.v0, dtype=float)
    for t in range(steps):
        Vp = np.maximum(Vt, 0.0)
        # Andersen full-truncation: drift uses Vp (the truncated variance)
        # too, not the un-truncated Vt. This keeps Vt's drift bounded and
        # matches the canonical scheme.
        Vt = (
            Vp
            + params.kappa * (params.theta - Vp) * dt
            + params.sigma * np.sqrt(Vp * dt) * Z2[t]
        )
        St = St * np.exp((r - q - 0.5 * Vp) * dt + np.sqrt(Vp * dt) * Z1[t])
    payoff = np.maximum(St - K, 0.0) if is_call else np.maximum(K - St, 0.0)
    disc = math.exp(-r * T)
    price = float(disc * payoff.mean())
    se = float(disc * payoff.std() / math.sqrt(len(payoff)))
    return {"price": price, "stderr": se, "method": "heston_mc",
            "paths": int(len(payoff)), "steps": int(steps)}


def heston_greeks(
    S: float, K: float, T: float, r: float, q: float,
    params: HestonParams,
    *,
    is_call: bool = True,
    paths: int = 20_000,
    steps: int = 80,
    seed: int | None = 42,
    bump_S: float = 0.01,
    bump_v: float = 0.01,
) -> dict[str, float]:
    """Finite-difference Heston greeks.

    D03-2026-05-24 (H20): callers (OVME, OSA, portfolio book) previously
    could only get a Heston *price* — no way to hedge a Heston-priced
    book. This wraps `heston_mc` with central differences.

    Delta:  (P(S*(1+b)) - P(S*(1-b))) / (2*b*S)
    Gamma:  (P(S*(1+b)) - 2*P(S) + P(S*(1-b))) / (b*S)^2
    Vega:   (P(v0+bv) - P(v0-bv)) / (2*bv)   — per 1.0 vol, scaled to /100.

    Reuses ``seed`` across bumps so common-random-numbers reduces the
    MC noise that would otherwise dominate small-bump greeks.
    """
    # Common-random-numbers: each call shares the seed so the noise
    # in P(S+) and P(S-) cancels in the differences.
    p0 = heston_mc(S, K, T, r, q, params, is_call=is_call, paths=paths,
                   steps=steps, seed=seed)["price"]
    p_up = heston_mc(S * (1 + bump_S), K, T, r, q, params, is_call=is_call,
                     paths=paths, steps=steps, seed=seed)["price"]
    p_dn = heston_mc(S * (1 - bump_S), K, T, r, q, params, is_call=is_call,
                     paths=paths, steps=steps, seed=seed)["price"]
    delta = (p_up - p_dn) / (2.0 * bump_S * S)
    gamma = (p_up - 2.0 * p0 + p_dn) / ((bump_S * S) ** 2)
    # Bump v0 (initial variance). The relationship sigma = sqrt(v0) is
    # nonlinear; we bump variance by ``bump_v`` and report per-vol-pt
    # vega via chain rule: d/dsigma = 2*sigma*d/dv.
    sigma = math.sqrt(max(params.v0, 1e-12))
    bump_v0 = max(2.0 * sigma * bump_v, 1e-6)
    params_up = HestonParams(kappa=params.kappa, theta=params.theta,
                              sigma=params.sigma, rho=params.rho,
                              v0=max(params.v0 + bump_v0, 1e-9))
    params_dn = HestonParams(kappa=params.kappa, theta=params.theta,
                              sigma=params.sigma, rho=params.rho,
                              v0=max(params.v0 - bump_v0, 1e-9))
    p_vup = heston_mc(S, K, T, r, q, params_up, is_call=is_call,
                      paths=paths, steps=steps, seed=seed)["price"]
    p_vdn = heston_mc(S, K, T, r, q, params_dn, is_call=is_call,
                      paths=paths, steps=steps, seed=seed)["price"]
    vega_per_vol = (p_vup - p_vdn) / (2.0 * bump_v0) * (2.0 * sigma)
    vega_per_pct = vega_per_vol / 100.0
    return {"price": p0, "delta": delta, "gamma": gamma,
            "vega": vega_per_pct, "method": "heston_fd",
            "paths": int(paths), "steps": int(steps)}
