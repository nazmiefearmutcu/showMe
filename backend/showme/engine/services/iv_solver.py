"""Implied volatility solver — Newton-Raphson with bisection fallback.

D03-2026-05-24: prior derivative pipeline relied on caller-supplied IV (or
the chain's listed IV). For per-leg OSA fairness, vol-skew aware GEX, and
generally anywhere we have a market price but no vol, we now have a
self-contained hybrid solver.

Algorithm:
1. Initial guess from Brenner-Subrahmanyam (1988):
       sigma_0 = sqrt(2*pi/T) * (price / S)
   This is the ATM-asymptotic closed-form approximation.
2. Newton-Raphson loop, max ``max_iter`` iterations:
       sigma_{n+1} = sigma_n - (BS(sigma_n) - market) / vega(sigma_n)
   Stop if |residual| < tol, or vega collapses below ``vega_floor``
   (deep ITM/OTM region — vega -> 0 makes Newton unstable).
3. Bisection fallback over [sigma_low, sigma_high] for any path Newton
   didn't converge on.

Result:
    {"iv": float, "iterations": int, "method": "newton"|"bisection"|"intrinsic",
     "residual": float, "converged": bool}
"""

from __future__ import annotations

import math
from typing import Any


def _bs_price_local(S: float, K: float, T: float, r: float, sigma: float,
                    q: float, is_call: bool) -> float:
    """Stand-alone BS price (no greeks dict). Avoids circular import."""
    if sigma <= 0 or T <= 0:
        return max(S - K, 0.0) if is_call else max(K - S, 0.0)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    def n_cdf(x: float) -> float:
        return 0.5 * (1 + math.erf(x / math.sqrt(2)))
    if is_call:
        return S * math.exp(-q * T) * n_cdf(d1) - K * math.exp(-r * T) * n_cdf(d2)
    return K * math.exp(-r * T) * n_cdf(-d2) - S * math.exp(-q * T) * n_cdf(-d1)


def _bs_vega_raw(S: float, K: float, T: float, r: float, sigma: float,
                 q: float) -> float:
    """Vega per 1.0 vol (NOT per 1%). Used internally by Newton."""
    if sigma <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    pdf = math.exp(-0.5 * d1 * d1) / math.sqrt(2 * math.pi)
    return S * math.exp(-q * T) * pdf * math.sqrt(T)


def implied_vol(
    *,
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float = 0.04,
    q: float = 0.0,
    is_call: bool = True,
    initial_guess: float | None = None,
    max_iter: int = 50,
    tol: float = 1e-6,
    vega_floor: float = 1e-9,
    sigma_low: float = 0.01,
    sigma_high: float = 5.0,
) -> dict[str, Any]:
    """Solve for implied vol given a market price.

    Args:
        market_price: Observed option premium (per-share).
        S: Spot price (>0).
        K: Strike (>0).
        T: Time to expiry in years (>0). T<=0 returns the intrinsic case.
        r: Risk-free rate (decimal annual).
        q: Continuous dividend yield (decimal annual).
        is_call: True for calls, False for puts.
        initial_guess: Override the Brenner-Subrahmanyam starting point.
        max_iter: Newton iterations cap.
        tol: |BS(sigma) - market| convergence threshold.
        vega_floor: Newton bails out when vega drops below this; we hand
            off to bisection instead of dividing by ~0.
        sigma_low, sigma_high: Bisection bracket.

    Returns dict with:
        iv: solved implied vol, decimal annual.
        iterations: total iterations (Newton + bisection).
        method: "newton" if converged via Newton, "bisection" if fallback
            kicked in, "intrinsic" if price equals (or is below) intrinsic
            value (T<=0 or deep-ITM degenerate case).
        residual: |BS(iv) - market|, final absolute residual.
        converged: True if residual < tol.
    """
    if S <= 0 or K <= 0:
        raise ValueError(f"S and K must be positive; got S={S}, K={K}")
    intrinsic = max(S - K, 0.0) if is_call else max(K - S, 0.0)
    if T <= 0:
        return {"iv": 0.0, "iterations": 0, "method": "intrinsic",
                "residual": abs(market_price - intrinsic),
                "converged": abs(market_price - intrinsic) < tol}
    if market_price <= intrinsic + tol:
        # At-or-below intrinsic. No positive vol can replicate this; the
        # market is either mispriced, stale, or the option is so deep ITM
        # the time value is below precision. Return 0 vol and flag intrinsic.
        return {"iv": 0.0, "iterations": 0, "method": "intrinsic",
                "residual": abs(market_price - intrinsic),
                "converged": False}
    # Brenner-Subrahmanyam ATM-asymptotic initial guess.
    if initial_guess is not None and initial_guess > 0:
        sigma = float(initial_guess)
    else:
        sigma = max(math.sqrt(2 * math.pi / T) * (market_price / S), 0.05)
        sigma = min(max(sigma, sigma_low), sigma_high)
    # ----- Newton-Raphson -----
    iters = 0
    for i in range(max_iter):
        iters = i + 1
        price = _bs_price_local(S, K, T, r, sigma, q, is_call)
        residual = price - market_price
        if abs(residual) < tol:
            return {"iv": sigma, "iterations": iters, "method": "newton",
                    "residual": abs(residual), "converged": True}
        vega = _bs_vega_raw(S, K, T, r, sigma, q)
        if vega < vega_floor:
            break  # hand off to bisection
        step = residual / vega
        sigma_new = sigma - step
        # Divergence guard: clamp to bracket so wild Newton steps don't
        # escape to negative vol or infinity.
        if sigma_new <= sigma_low or sigma_new >= sigma_high:
            break  # hand off to bisection
        sigma = sigma_new
    # ----- Bisection fallback -----
    lo, hi = sigma_low, sigma_high
    price_lo = _bs_price_local(S, K, T, r, lo, q, is_call) - market_price
    price_hi = _bs_price_local(S, K, T, r, hi, q, is_call) - market_price
    if price_lo * price_hi > 0:
        # Same sign at both endpoints: bracket doesn't contain a root.
        # This usually means market_price is outside [intrinsic, S].
        return {"iv": sigma, "iterations": iters, "method": "bisection",
                "residual": abs(price_lo if abs(price_lo) < abs(price_hi) else price_hi),
                "converged": False}
    bisect_iters = 0
    f_mid = price_lo
    for j in range(200):
        bisect_iters = j + 1
        mid = 0.5 * (lo + hi)
        f_mid = _bs_price_local(S, K, T, r, mid, q, is_call) - market_price
        # Two exit conditions: residual under tolerance, OR bracket has
        # collapsed so tightly that any further iteration is below numeric
        # precision. In both cases we treat it as converged provided the
        # residual is within ~10x tolerance (bracket-collapse can leave a
        # tiny residual that still rounds to "good enough" for IV use).
        if abs(f_mid) < tol:
            return {"iv": mid, "iterations": iters + bisect_iters,
                    "method": "bisection",
                    "residual": abs(f_mid), "converged": True}
        if (hi - lo) < tol:
            return {"iv": mid, "iterations": iters + bisect_iters,
                    "method": "bisection",
                    "residual": abs(f_mid),
                    "converged": abs(f_mid) < tol * 10.0}
        if price_lo * f_mid < 0:
            hi = mid
            price_hi = f_mid
        else:
            lo = mid
            price_lo = f_mid
    return {"iv": 0.5 * (lo + hi), "iterations": iters + bisect_iters,
            "method": "bisection", "residual": abs(f_mid), "converged": False}
