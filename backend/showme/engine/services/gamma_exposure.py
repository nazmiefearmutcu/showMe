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

Honesty (wc1-g06 GEX#5): no implied vol or expiry is invented. A contract
without a usable strike, implied vol or expiry is left out of the sums and
counted in ``excluded``; a missing or non-finite open interest counts as zero
and is counted in ``oi_missing``. Both counts are returned for disclosure.

Black-Scholes gamma:
    γ = N'(d1) / (S σ √T)
where d1 = [ln(S/K) + (r + σ²/2) T] / (σ √T)
"""

from __future__ import annotations

import math
from datetime import datetime, timezone
from typing import Any
from zoneinfo import ZoneInfo


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


_EXPIRY_TZ = ZoneInfo("America/New_York")


def time_to_expiry_years(expiry: Any, now: datetime) -> float | None:
    """Years from ``now`` to the listed close of an expiry date.

    Every expiry (today or later) runs to the 16:00 America/New_York equity
    option close, so T is consistent across expiries and the same-day branch
    is not a special case. Returns None when ``expiry`` is not a date.
    """
    try:
        day = datetime.fromisoformat(str(expiry)[:10]).date()
    except (TypeError, ValueError):
        return None
    close_local = datetime(day.year, day.month, day.day, 16, 0, tzinfo=_EXPIRY_TZ)
    seconds = (close_local.astimezone(timezone.utc) - now).total_seconds()
    return max(seconds / (365 * 86400), 1e-9)


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

# Smallest observed implied vol (annualized decimal, 0.01%) that is priced as
# given. Below it the Black-Scholes term sigma*sqrt(T) is numerically degenerate,
# so such a contract is excluded and counted in ``excluded.implied_vol``.
MIN_USABLE_IV = 1e-4


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


def _finite_positive(value: Any) -> float | None:
    """A finite number > 0, else None (missing, NaN, inf, zero or invalid)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _finite_nonnegative(value: Any) -> float | None:
    """A finite number >= 0, else None. Used for open interest only."""
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number >= 0 else None


def chain_gex(
    *, spot: float,
    calls: list[dict[str, Any]],
    puts: list[dict[str, Any]],
    contract_size: int = 100,
    rate: float = 0.04,
    div_yield: float = 0.0,
) -> dict[str, Any]:
    """Compute per-strike gamma exposure dollar terms.

    Each call/put dict is expected to have ``strike``, ``openInterest`` (or ``oi``),
    ``impliedVolatility`` (or ``iv``), and ``expiry`` (datetime str / "YYYY-MM-DD")
    or ``T`` (years).

    A contract whose strike, implied vol or time to expiry is missing or invalid
    is excluded (never priced at a substitute vol or term) and counted in
    ``excluded``. A missing open interest contributes zero and is counted in
    ``oi_missing``. ``contracts_used`` counts contracts that entered the sums.
    """
    now = datetime.now(timezone.utc)
    excluded = {"strike": 0, "implied_vol": 0, "expiry": 0}
    oi_missing = 0

    def _T(opt: dict[str, Any]) -> float | None:
        if opt.get("T") is not None:
            return _finite_positive(opt.get("T"))
        exp = opt.get("expiry") or opt.get("expiration") or opt.get("expiration_date")
        if not exp:
            return None
        # Same 16:00 ET close for today and future expiries (GEX#4).
        return time_to_expiry_years(exp, now)

    def _vol(opt: dict[str, Any]) -> float | None:
        # The observed market IV is used as it is. An IV too small to price
        # safely is not lifted to a floor (that would substitute a constant for
        # observed data); the contract is excluded and counted instead (GEX#5).
        for key in ("impliedVolatility", "iv"):
            v = _finite_positive(opt.get(key))
            if v is not None:
                return v if v >= MIN_USABLE_IV else None
        return None

    def _oi(opt: dict[str, Any]) -> float | None:
        for key in ("openInterest", "oi"):
            v = _finite_nonnegative(opt.get(key))
            if v is not None:
                return v
        return None

    # Per-side contract terms, kept so total GEX can be re-evaluated at
    # hypothetical spots with the same chain (fixed IV, OI and expiry).
    call_terms: list[tuple[float, float, float, float]] = []  # (K, vol, T, oi)
    put_terms: list[tuple[float, float, float, float]] = []

    def _collect(options: list[dict[str, Any]], terms: list[tuple[float, float, float, float]]) -> None:
        nonlocal oi_missing
        for opt in options:
            K = _finite_positive(opt.get("strike"))
            if K is None:
                excluded["strike"] += 1
                continue
            vol = _vol(opt)
            if vol is None:
                excluded["implied_vol"] += 1
                continue
            T = _T(opt)
            if T is None:
                excluded["expiry"] += 1
                continue
            oi = _oi(opt)
            if oi is None:
                oi_missing += 1
                oi = 0.0
            terms.append((K, vol, T, oi))

    _collect(calls, call_terms)
    _collect(puts, put_terms)

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
        "contracts_used": len(call_terms) + len(put_terms),
        "excluded": excluded,
        "oi_missing": oi_missing,
    }
