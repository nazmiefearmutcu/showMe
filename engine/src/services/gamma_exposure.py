"""Gamma Exposure (GEX) calculation.

Computes per-strike dealer gamma exposure (assuming dealer is short call OI
and long put OI) and aggregates the chain into:
- gex_per_strike: dict of strike → notional gamma per 1% move
- net_gex: signed aggregate
- gex_flip: zero-gamma strike (where dealer hedging flips polarity)
- call_wall / put_wall: largest positive/negative concentrations
- gamma_curve: per-strike cumulative gex (for chart)

Black-Scholes gamma:
    γ = N'(d1) / (S σ √T)
where d1 = [ln(S/K) + (r + σ²/2) T] / (σ √T)
"""

from __future__ import annotations

import math
from typing import Any


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_gamma(spot: float, strike: float, vol: float, T: float, r: float = 0.04) -> float:
    if spot <= 0 or strike <= 0 or vol <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r + 0.5 * vol * vol) * T) / (vol * math.sqrt(T))
    return _norm_pdf(d1) / (spot * vol * math.sqrt(T))


def chain_gex(
    *, spot: float,
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    contract_size: int = 100,
    rate: float = 0.04,
    default_vol: float = 0.30,
) -> dict[str, Any]:
    """Compute per-strike gamma exposure dollar terms.

    Each call/put dict is expected to have ``strike``, ``openInterest`` (or ``oi``),
    ``impliedVolatility`` (or ``iv``), and ``expiry`` (datetime str / "YYYY-MM-DD")
    or ``T`` (years).
    """
    from datetime import datetime
    today = datetime.utcnow().date()

    def _T(opt: dict[str, Any]) -> float:
        T = opt.get("T")
        if T is not None:
            return float(T)
        exp = opt.get("expiry") or opt.get("expiration") or opt.get("expiration_date")
        if exp:
            try:
                d = datetime.fromisoformat(str(exp)[:10]).date()
                return max((d - today).days, 0) / 365.0
            except Exception:
                pass
        return 30 / 365.0

    def _vol(opt: dict[str, Any]) -> float:
        v = opt.get("impliedVolatility") or opt.get("iv") or default_vol
        try:
            v = float(v)
            return max(v, 0.05)
        except Exception:
            return default_vol

    def _oi(opt: dict[str, Any]) -> float:
        v = opt.get("openInterest") or opt.get("oi") or 0
        try:
            return float(v)
        except Exception:
            return 0.0

    per_strike: dict[float, float] = {}
    call_gex_total = 0.0
    put_gex_total = 0.0
    for c in calls:
        K = float(c.get("strike") or 0)
        if K <= 0:
            continue
        gamma = bs_gamma(spot, K, _vol(c), _T(c), rate)
        # Dealers short calls → negative gamma to dealers; we report dealer-perspective.
        oi = _oi(c)
        gex = -gamma * oi * contract_size * (spot ** 2) * 0.01    # $ per 1% move
        per_strike[K] = per_strike.get(K, 0.0) + gex
        call_gex_total += gex
    for p in puts:
        K = float(p.get("strike") or 0)
        if K <= 0:
            continue
        gamma = bs_gamma(spot, K, _vol(p), _T(p), rate)
        # Dealers long puts → positive gamma to dealers.
        oi = _oi(p)
        gex = +gamma * oi * contract_size * (spot ** 2) * 0.01
        per_strike[K] = per_strike.get(K, 0.0) + gex
        put_gex_total += gex
    net = sum(per_strike.values())
    sorted_strikes = sorted(per_strike.items(), key=lambda kv: kv[0])
    # Gamma flip = first strike where cumulative GEX changes sign as price rises through it.
    flip_strike = None
    cumulative = 0.0
    last_sign = None
    for K, gex in sorted_strikes:
        cumulative += gex
        sign = 1 if cumulative > 0 else (-1 if cumulative < 0 else 0)
        if last_sign is not None and sign != 0 and sign != last_sign:
            flip_strike = K
            break
        if sign != 0:
            last_sign = sign
    # Walls
    call_wall = max(per_strike.items(), key=lambda kv: kv[1], default=(None, 0))
    put_wall = min(per_strike.items(), key=lambda kv: kv[1], default=(None, 0))
    return {
        "spot": spot,
        "net_gex": net,
        "call_gex_total": call_gex_total,
        "put_gex_total": put_gex_total,
        "gex_per_strike": [{"strike": k, "gex": v} for k, v in sorted_strikes],
        "gamma_flip": flip_strike,
        "call_wall": {"strike": call_wall[0], "gex": call_wall[1]},
        "put_wall": {"strike": put_wall[0], "gex": put_wall[1]},
        "n_strikes": len(sorted_strikes),
    }
