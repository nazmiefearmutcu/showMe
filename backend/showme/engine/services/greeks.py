"""Black-Scholes greeks (no SciPy / py_vollib).

Functions (all per-share, single contract):
    bs_d1(S, K, vol, T, r=0.04, q=0.0)
    bs_call_price / bs_put_price
    bs_delta_call / bs_delta_put   — per 1.0 underlying unit
    bs_gamma                       — per 1.0 underlying unit
    bs_vega                        — per 1% vol move  (i.e. already / 100)
    bs_theta_call / bs_theta_put   — per calendar day (already / 365)
    bs_rho_call / bs_rho_put       — per 1 bp rate move (already / 10000)

Trader-readable unit convention (D03-2026-05-24):
  Prior versions emitted greeks in "math units" (vega per 1.00 vol,
  rho per 1.00 rate, theta per year) and let the caller scale them.
  position_greeks then divided theta by 365 but forgot vega/rho — which
  produced 100x over-stated vega and 10,000x over-stated rho on the
  portfolio book pane. To fix this once, ALL greek functions in this
  module now return trader-readable units; callers (and tests) just
  multiply by qty * contract_size.

Validation guards:
  S<=0 or K<=0 -> raise ValueError (no silent clamp; old _safe(K, 1e-12)
  was warping log-domain for penny stocks).
  vol<=0 OR T<=0 -> clamped to 1e-9 (consistent with ovme._bs_price's
  intrinsic-only branch; raw math wouldn't define vega/theta otherwise).

Aggregation:
    aggregate_book(positions) — sum delta/gamma/vega/theta/rho across an
    option book; positions is a list of {kind: "call"|"put", quantity,
    contract_size, spot, strike, vol, T, r, q}.
"""

from __future__ import annotations

import logging
import math
from typing import Any


SQRT_2PI = math.sqrt(2 * math.pi)

LOG = logging.getLogger("showme.engine.services.greeks")

# Scaling factors used to render greeks in trader-readable units.
# Vega per 1% vol move = raw_vega / VEGA_VOL_PT  (e.g. 0.197 not 19.7)
# Rho per 1 bp rate    = raw_rho  / RHO_BPS      (e.g. 0.011 not 110)
# Theta per day        = raw_theta / DAYS_PER_YEAR
VEGA_VOL_PT = 100.0
RHO_BPS = 10_000.0
DAYS_PER_YEAR = 365.0


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _norm_cdf(x: float) -> float:
    """Abramowitz & Stegun erf-based CDF (no SciPy)."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _validate_S_K(S: float, K: float) -> None:
    """D03-2026-05-24: explicit reject. Old code used _safe(x, 1e-12) which
    silently warped log(S/K) for penny stocks and produced nonsense greeks.
    Caller now sees a ValueError they can wrap, instead of a smooth lie."""
    S = float(S)
    K = float(K)
    if not (S > 0.0) or not (K > 0.0):
        raise ValueError(
            f"S and K must be positive; got S={S}, K={K}. "
            "If you need a NaN fallback use ovme._bs_price (returns an error marker).")


def _safe_vol_T(vol: float, T: float) -> tuple[float, float]:
    """D03-2026-05-24: vol=0 used to ZeroDivisionError in bs_d1. Mirror
    ovme._bs_price's intrinsic-only branch instead — clamp both inputs so
    every consumer (gamma/vega/theta/rho) gets a defined value."""
    return max(float(vol), 1e-9), max(float(T), 1e-9)


def bs_d1(S: float, K: float, vol: float, T: float, r: float = 0.04,
          q: float = 0.0) -> float:
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    return (math.log(S / K) + (r - q + 0.5 * vol * vol) * T) / (
        vol * math.sqrt(T))


def bs_d2(S: float, K: float, vol: float, T: float, r: float = 0.04,
          q: float = 0.0) -> float:
    vol_c, T_c = _safe_vol_T(vol, T)
    return bs_d1(S, K, vol_c, T_c, r, q) - vol_c * math.sqrt(T_c)


def bs_call_price(S, K, vol, T, r=0.04, q=0.0) -> float:
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    d1 = bs_d1(S, K, vol, T, r, q)
    d2 = d1 - vol * math.sqrt(T)
    return S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bs_put_price(S, K, vol, T, r=0.04, q=0.0) -> float:
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    d1 = bs_d1(S, K, vol, T, r, q)
    d2 = d1 - vol * math.sqrt(T)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * math.exp(-q * T) * _norm_cdf(-d1)


def bs_delta_call(S, K, vol, T, r=0.04, q=0.0) -> float:
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    return math.exp(-q * T) * _norm_cdf(bs_d1(S, K, vol, T, r, q))


def bs_delta_put(S, K, vol, T, r=0.04, q=0.0) -> float:
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    return -math.exp(-q * T) * _norm_cdf(-bs_d1(S, K, vol, T, r, q))


def bs_gamma(S, K, vol, T, r=0.04, q=0.0) -> float:
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    return math.exp(-q * T) * _norm_pdf(bs_d1(S, K, vol, T, r, q)) / (
        S * vol * math.sqrt(T))


def bs_vega(S, K, vol, T, r=0.04, q=0.0) -> float:
    """Per 1% vol move (already divided by 100).

    D03-2026-05-24: prior docstring said "per 1-volatility-point" but math
    returned per 1.00 vol move — caller position_greeks didn't /100 either,
    so the portfolio pane reported $19.72 vega where the correct value was
    $0.197 per 1% IV move (100x over-stated).
    """
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    raw = S * math.exp(-q * T) * _norm_pdf(bs_d1(S, K, vol, T, r, q)) * math.sqrt(T)
    return raw / VEGA_VOL_PT


def bs_theta_call(S, K, vol, T, r=0.04, q=0.0) -> float:
    """Per calendar day (already divided by 365)."""
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    d1 = bs_d1(S, K, vol, T, r, q)
    d2 = d1 - vol * math.sqrt(T)
    raw = (
        -math.exp(-q * T) * S * _norm_pdf(d1) * vol / (2 * math.sqrt(T))
        - r * K * math.exp(-r * T) * _norm_cdf(d2)
        + q * S * math.exp(-q * T) * _norm_cdf(d1)
    )
    return raw / DAYS_PER_YEAR


def bs_theta_put(S, K, vol, T, r=0.04, q=0.0) -> float:
    """Per calendar day (already divided by 365)."""
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    d1 = bs_d1(S, K, vol, T, r, q)
    d2 = d1 - vol * math.sqrt(T)
    raw = (
        -math.exp(-q * T) * S * _norm_pdf(d1) * vol / (2 * math.sqrt(T))
        + r * K * math.exp(-r * T) * _norm_cdf(-d2)
        - q * S * math.exp(-q * T) * _norm_cdf(-d1)
    )
    return raw / DAYS_PER_YEAR


def bs_rho_call(S, K, vol, T, r=0.04, q=0.0) -> float:
    """Per 1 bp rate move (already divided by 10000).

    D03-2026-05-24: prior version returned per 1.00 rate move; position
    book scaled it through unchanged, so the portfolio pane reported $110
    rho where the correct value was $0.011 per 1 bp rate move (10000x
    over-stated). 10000 is the standard street convention for rho-bps.
    """
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    raw = K * T * math.exp(-r * T) * _norm_cdf(bs_d2(S, K, vol, T, r, q))
    return raw / RHO_BPS


def bs_rho_put(S, K, vol, T, r=0.04, q=0.0) -> float:
    """Per 1 bp rate move (already divided by 10000)."""
    _validate_S_K(S, K)
    vol, T = _safe_vol_T(vol, T)
    raw = -K * T * math.exp(-r * T) * _norm_cdf(-bs_d2(S, K, vol, T, r, q))
    return raw / RHO_BPS


_DEFAULT_VOL = 0.30
_DEFAULT_T_DAYS = 30  # ≈ 1 month


def position_greeks(pos: dict[str, Any]) -> dict[str, Any]:
    """Compute book-level greeks for one position.

    Returns trader-readable units already scaled by quantity * contract_size:
      delta: per 1.0 underlying move (USD)
      gamma: per 1.0 underlying move
      vega:  per 1% vol move (USD)
      theta: per day (USD)
      rho:   per 1 bp rate move (USD)

    Missing vol/T are silently substituted with defaults (vol=0.30,
    T=30 days). D03-2026-05-24: each substitution is now reported in the
    returned ``assumptions_used`` list so the UI can flag synthetic greeks
    and also logged at WARNING level.
    """
    kind = (pos.get("kind") or "call").lower()
    S = float(pos["spot"])
    K = float(pos["strike"])
    assumptions_used: list[str] = []
    raw_vol = pos.get("vol")
    if raw_vol is None:
        vol = _DEFAULT_VOL
        assumptions_used.append(f"vol=default {_DEFAULT_VOL:.2f}")
        LOG.warning("position_greeks: missing vol, using default %.2f for kind=%s strike=%.2f",
                    _DEFAULT_VOL, kind, K)
    else:
        vol = float(raw_vol)
    raw_T = pos.get("T")
    if raw_T is None:
        T = _DEFAULT_T_DAYS / 365.0
        assumptions_used.append(f"T=default {_DEFAULT_T_DAYS}d")
        LOG.warning("position_greeks: missing T, using default %dd for kind=%s strike=%.2f",
                    _DEFAULT_T_DAYS, kind, K)
    else:
        T = float(raw_T)
    r = float(pos.get("r", 0.04))
    q = float(pos.get("q", 0.0))
    qty = float(pos.get("quantity", 1))
    sz = int(pos.get("contract_size", 100))
    multi = qty * sz
    if kind == "call":
        out = {
            "kind": "call",
            "delta": bs_delta_call(S, K, vol, T, r, q) * multi,
            "gamma": bs_gamma(S, K, vol, T, r, q) * multi,
            "vega": bs_vega(S, K, vol, T, r, q) * multi,
            "theta": bs_theta_call(S, K, vol, T, r, q) * multi,
            "rho": bs_rho_call(S, K, vol, T, r, q) * multi,
        }
    else:
        out = {
            "kind": "put",
            "delta": bs_delta_put(S, K, vol, T, r, q) * multi,
            "gamma": bs_gamma(S, K, vol, T, r, q) * multi,
            "vega": bs_vega(S, K, vol, T, r, q) * multi,
            "theta": bs_theta_put(S, K, vol, T, r, q) * multi,
            "rho": bs_rho_put(S, K, vol, T, r, q) * multi,
        }
    if assumptions_used:
        out["assumptions_used"] = assumptions_used
    return out


def aggregate_book(positions: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sums = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    aggregate_assumptions: list[str] = []
    for p in positions:
        try:
            g = position_greeks(p)
        except Exception as e:
            rows.append({"error": str(e), **{k: p.get(k) for k in ("symbol", "kind", "strike")}})
            continue
        rows.append({
            **{k: p.get(k) for k in ("symbol", "kind", "strike", "T", "vol",
                                      "spot", "quantity", "contract_size")},
            **g,
        })
        for k in sums:
            sums[k] += g.get(k, 0.0)
        if g.get("assumptions_used"):
            for a in g["assumptions_used"]:
                tag = f"{p.get('symbol', '?')}: {a}"
                if tag not in aggregate_assumptions:
                    aggregate_assumptions.append(tag)
    out: dict[str, Any] = {
        "positions": rows,
        "totals": sums,
        "n": len(rows),
        "units": {
            "delta": "per 1.0 underlying move (USD)",
            "gamma": "per 1.0 underlying move",
            "vega": "per 1% vol move (USD)",
            "theta": "per calendar day (USD)",
            "rho": "per 1 bp rate move (USD)",
        },
    }
    if aggregate_assumptions:
        out["assumptions_used"] = aggregate_assumptions
    return out
