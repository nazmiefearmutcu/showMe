"""Gamma Exposure (GEX) calculation.

Computes per-strike dealer gamma exposure (assuming dealer is short call OI
and long put OI) and aggregates the chain into:
- gex_per_strike: dict of strike → net notional gamma per 1% move
- net_gex: signed aggregate
- gamma_flip: spot level where total dealer GEX changes sign (zero crossing of
  net GEX re-evaluated on a ±10% spot grid with the same chain; None if none)
- call_wall / put_wall: strike with the largest absolute dealer call / put
  gamma exposure, reported with that side's own GEX value
- gex_per_strike: per-strike net values (for chart)

Black-Scholes gamma:
    γ = N'(d1) / (S σ √T)
where d1 = [ln(S/K) + (r + σ²/2) T] / (σ √T)
"""

from __future__ import annotations

import math
from typing import Any


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def bs_gamma(spot: float, strike: float, vol: float, T: float, r: float = 0.04,
             q: float = 0.0) -> float:
    """Black-Scholes-Merton gamma with continuous dividend yield q.

    D03-2026-05-24 (H7): formula now includes ``-q`` in the drift term and
    multiplies by ``exp(-qT)``. Old SPX/ETF GEX understated by ~q*T ≈ 1-2%
    on long-dated strikes because q was treated as 0.
    """
    if spot <= 0 or strike <= 0 or vol <= 0 or T <= 0:
        return 0.0
    d1 = (math.log(spot / strike) + (r - q + 0.5 * vol * vol) * T) / (vol * math.sqrt(T))
    return math.exp(-q * T) * _norm_pdf(d1) / (spot * vol * math.sqrt(T))


_FLIP_GRID_PCT = 0.10
_FLIP_GRID_STEP = 0.0025


def _gamma_flip_spot_grid(spot: float, total_gex_at: Any) -> float | None:
    """Spot level nearest ``spot`` where total dealer GEX changes sign.

    Evaluates ``total_gex_at(s)`` on a grid of ±10% around spot and linearly
    interpolates each sign change. Returns None when no crossing lies inside
    the grid, so callers can report "no crossing in range" honestly.
    """
    if spot <= 0:
        return None
    steps = int(round(_FLIP_GRID_PCT / _FLIP_GRID_STEP))
    grid = [spot * (1.0 + _FLIP_GRID_STEP * i) for i in range(-steps, steps + 1)]
    values = [total_gex_at(s) for s in grid]
    # Sign of each grid value (0 for exact zero). A crossing needs a strict
    # sign change between the nearest non-zero values on either side, so a
    # flat zero (no open interest) or a one-sided chain never yields a flip.
    signs = [0 if v == 0 else (1 if v > 0 else -1) for v in values]
    nonzero_idx = [i for i, s in enumerate(signs) if s != 0]
    if not nonzero_idx:
        return None
    best: float | None = None
    for i in range(len(grid) - 1):
        v0, v1 = values[i], values[i + 1]
        if v0 * v1 < 0:
            cross = grid[i] + (grid[i + 1] - grid[i]) * v0 / (v0 - v1)
        elif v0 == 0 and v1 != 0:
            # Exact zero at grid[i]: genuine crossing only if the nearest
            # non-zero value to the left and to the right differ in sign.
            left = [j for j in nonzero_idx if j < i]
            right = [j for j in nonzero_idx if j > i]
            if not left or not right:
                continue
            if signs[left[-1]] == signs[right[0]]:
                continue
            cross = grid[i]
        else:
            continue
        if best is None or abs(cross - spot) < abs(best - spot):
            best = cross
    return round(best, 2) if best is not None else None


def chain_gex(
    *, spot: float,
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    contract_size: int = 100,
    rate: float = 0.04,
    default_vol: float = 0.30,
    div_yield: float = 0.0,
) -> dict[str, Any]:
    """Compute per-strike gamma exposure dollar terms.

    Each call/put dict is expected to have ``strike``, ``openInterest`` (or ``oi``),
    ``impliedVolatility`` (or ``iv``), and ``expiry`` (datetime str / "YYYY-MM-DD")
    or ``T`` (years).

    D03-2026-05-24 (H7+H8): ``div_yield`` is now a first-class parameter
    (SPX ≈ 1.5% — 0DTE bias was material). Intraday expiries now compute
    fractional days via UTC current time, so 0DTE option gamma is finite
    and not 0 once the calendar rolls.
    """
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    today = now.date()

    def _T(opt: dict[str, Any]) -> float:
        T = opt.get("T")
        if T is not None:
            return max(float(T), 1e-9)
        exp = opt.get("expiry") or opt.get("expiration") or opt.get("expiration_date")
        if exp:
            try:
                d = datetime.fromisoformat(str(exp)[:10]).date()
                if d <= today:
                    # 0DTE / late-day: fractional intraday time-to-expiry.
                    # Assume listed equity-option expiry is 16:00 UTC-5
                    # (US close ≈ 21:00 UTC). For non-US instruments the
                    # caller should pass an explicit ``T``.
                    expiry_dt = datetime(d.year, d.month, d.day, 21, 0,
                                         tzinfo=timezone.utc)
                    seconds = (expiry_dt - now).total_seconds()
                    return max(seconds / (365 * 86400), 1e-9)
                return (d - today).days / 365.0
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

    # Per-side contract terms, kept so total GEX can be re-evaluated at
    # hypothetical spots with the same chain (fixed IV, OI and expiry).
    call_terms: list[tuple[float, float, float, float]] = []  # (K, vol, T, oi)
    put_terms: list[tuple[float, float, float, float]] = []
    for c in calls:
        K = float(c.get("strike") or 0)
        if K <= 0:
            continue
        call_terms.append((K, _vol(c), _T(c), _oi(c)))
    for p in puts:
        K = float(p.get("strike") or 0)
        if K <= 0:
            continue
        put_terms.append((K, _vol(p), _T(p), _oi(p)))

    def _side_gex(s: float, terms: list[tuple[float, float, float, float]], sign: float,
                  ) -> dict[float, float]:
        out: dict[float, float] = {}
        for K, vol, T, oi in terms:
            gamma = bs_gamma(s, K, vol, T, rate, div_yield)
            # Dealers short calls (sign -1), long puts (sign +1); $ per 1% move.
            out[K] = out.get(K, 0.0) + sign * gamma * oi * contract_size * (s ** 2) * 0.01
        return out

    call_by_strike = _side_gex(spot, call_terms, -1.0)
    put_by_strike = _side_gex(spot, put_terms, +1.0)
    call_gex_total = sum(call_by_strike.values())
    put_gex_total = sum(put_by_strike.values())
    per_strike: dict[float, float] = {}
    for side in (call_by_strike, put_by_strike):
        for K, v in side.items():
            per_strike[K] = per_strike.get(K, 0.0) + v
    net = sum(per_strike.values())
    sorted_strikes = sorted(per_strike.items(), key=lambda kv: kv[0])

    # Gamma flip: zero crossing of TOTAL dealer GEX as spot moves (same chain).
    flip_strike = _gamma_flip_spot_grid(
        spot,
        lambda s: sum(_side_gex(s, call_terms, -1.0).values())
        + sum(_side_gex(s, put_terms, +1.0).values()),
    )
    # Walls: largest absolute dealer GEX on each side, with that side's value.
    call_wall = max(call_by_strike.items(), key=lambda kv: abs(kv[1]), default=(None, 0.0))
    put_wall = max(put_by_strike.items(), key=lambda kv: abs(kv[1]), default=(None, 0.0))
    return {
        "spot": spot,
        "net_gex": net,
        "call_gex_total": call_gex_total,
        "put_gex_total": put_gex_total,
        "gex_per_strike": [{"strike": k, "gex": v} for k, v in sorted_strikes],
        "gamma_flip": flip_strike,
        "gamma_flip_method": "spot_grid_zero_crossing",
        "call_wall": {"strike": call_wall[0], "gex": call_wall[1]},
        "put_wall": {"strike": put_wall[0], "gex": put_wall[1]},
        "n_strikes": len(sorted_strikes),
    }
