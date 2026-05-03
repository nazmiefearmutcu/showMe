"""Black-Scholes greeks (no SciPy / py_vollib).

Functions:
    bs_d1(S, K, vol, T, r=0.04, q=0.0)
    bs_call_price / bs_put_price
    bs_delta_call / bs_delta_put
    bs_gamma  (= dual)
    bs_vega   (per-1-vol-pt)
    bs_theta_call / bs_theta_put (per-day)
    bs_rho_call / bs_rho_put

Aggregation:
    aggregate_book(positions) — sum delta/gamma/vega/theta across an option
    book; positions is a list of {kind: "call"|"put", quantity, contract_size,
    spot, strike, vol, T, r, q}.
"""

from __future__ import annotations

import math
from typing import Any


SQRT_2PI = math.sqrt(2 * math.pi)


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / SQRT_2PI


def _norm_cdf(x: float) -> float:
    """Abramowitz & Stegun erf-based CDF (no SciPy)."""
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))


def _safe(x: float, low: float = 1e-12) -> float:
    return max(float(x), low)


def bs_d1(S: float, K: float, vol: float, T: float, r: float = 0.04,
          q: float = 0.0) -> float:
    return (math.log(_safe(S) / _safe(K)) + (r - q + 0.5 * vol * vol) * T) / (
        vol * math.sqrt(_safe(T)))


def bs_d2(S: float, K: float, vol: float, T: float, r: float = 0.04,
          q: float = 0.0) -> float:
    return bs_d1(S, K, vol, T, r, q) - vol * math.sqrt(_safe(T))


def bs_call_price(S, K, vol, T, r=0.04, q=0.0) -> float:
    d1 = bs_d1(S, K, vol, T, r, q)
    d2 = d1 - vol * math.sqrt(_safe(T))
    return S * math.exp(-q * T) * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)


def bs_put_price(S, K, vol, T, r=0.04, q=0.0) -> float:
    d1 = bs_d1(S, K, vol, T, r, q)
    d2 = d1 - vol * math.sqrt(_safe(T))
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * math.exp(-q * T) * _norm_cdf(-d1)


def bs_delta_call(S, K, vol, T, r=0.04, q=0.0) -> float:
    return math.exp(-q * T) * _norm_cdf(bs_d1(S, K, vol, T, r, q))


def bs_delta_put(S, K, vol, T, r=0.04, q=0.0) -> float:
    return -math.exp(-q * T) * _norm_cdf(-bs_d1(S, K, vol, T, r, q))


def bs_gamma(S, K, vol, T, r=0.04, q=0.0) -> float:
    return math.exp(-q * T) * _norm_pdf(bs_d1(S, K, vol, T, r, q)) / (
        S * vol * math.sqrt(_safe(T)))


def bs_vega(S, K, vol, T, r=0.04, q=0.0) -> float:
    """Per 1-volatility-point (i.e. divide by 100 for per-1%-move)."""
    return S * math.exp(-q * T) * _norm_pdf(bs_d1(S, K, vol, T, r, q)) * math.sqrt(_safe(T))


def bs_theta_call(S, K, vol, T, r=0.04, q=0.0) -> float:
    """Per year — divide by 365 for per-day decay."""
    d1 = bs_d1(S, K, vol, T, r, q)
    d2 = d1 - vol * math.sqrt(_safe(T))
    return (
        -math.exp(-q * T) * S * _norm_pdf(d1) * vol / (2 * math.sqrt(_safe(T)))
        - r * K * math.exp(-r * T) * _norm_cdf(d2)
        + q * S * math.exp(-q * T) * _norm_cdf(d1)
    )


def bs_theta_put(S, K, vol, T, r=0.04, q=0.0) -> float:
    d1 = bs_d1(S, K, vol, T, r, q)
    d2 = d1 - vol * math.sqrt(_safe(T))
    return (
        -math.exp(-q * T) * S * _norm_pdf(d1) * vol / (2 * math.sqrt(_safe(T)))
        + r * K * math.exp(-r * T) * _norm_cdf(-d2)
        - q * S * math.exp(-q * T) * _norm_cdf(-d1)
    )


def bs_rho_call(S, K, vol, T, r=0.04, q=0.0) -> float:
    return K * T * math.exp(-r * T) * _norm_cdf(bs_d2(S, K, vol, T, r, q))


def bs_rho_put(S, K, vol, T, r=0.04, q=0.0) -> float:
    return -K * T * math.exp(-r * T) * _norm_cdf(-bs_d2(S, K, vol, T, r, q))


def position_greeks(pos: dict[str, Any]) -> dict[str, Any]:
    kind = (pos.get("kind") or "call").lower()
    S = float(pos["spot"])
    K = float(pos["strike"])
    vol = float(pos.get("vol", 0.30))
    T = float(pos.get("T", 30 / 365))
    r = float(pos.get("r", 0.04))
    q = float(pos.get("q", 0.0))
    qty = float(pos.get("quantity", 1))
    sz = int(pos.get("contract_size", 100))
    multi = qty * sz
    if kind == "call":
        return {
            "kind": "call",
            "delta": bs_delta_call(S, K, vol, T, r, q) * multi,
            "gamma": bs_gamma(S, K, vol, T, r, q) * multi,
            "vega": bs_vega(S, K, vol, T, r, q) * multi,
            "theta": bs_theta_call(S, K, vol, T, r, q) * multi / 365.0,
            "rho": bs_rho_call(S, K, vol, T, r, q) * multi,
        }
    return {
        "kind": "put",
        "delta": bs_delta_put(S, K, vol, T, r, q) * multi,
        "gamma": bs_gamma(S, K, vol, T, r, q) * multi,
        "vega": bs_vega(S, K, vol, T, r, q) * multi,
        "theta": bs_theta_put(S, K, vol, T, r, q) * multi / 365.0,
        "rho": bs_rho_put(S, K, vol, T, r, q) * multi,
    }


def aggregate_book(positions: list[dict[str, Any]]) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    sums = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
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
    return {"positions": rows, "totals": sums, "n": len(rows)}
