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
    """Monte Carlo Heston with full-truncation Euler scheme."""
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
        Vt = (
            Vt
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
