"""D03-2026-05-24: greek unit drift fix.

Pin the trader-readable unit convention across services/greeks.py vs
functions/derivative/ovme.py. Same option, two callers — same numbers.

Bugs covered:
- C1: position_greeks scaled theta /365 but left vega + rho raw (100x +
      10,000x over-stated).
- C3: bs_d1 had no vol=0 guard; raised ZeroDivisionError.
- C6: bs_vega/bs_rho were per-1.00 vol / per-1.00 rate; ovme returned
      per-1% / per-rate-point. The two diverged silently.
- C10: position_greeks now reports `assumptions_used` when vol/T missing.
- C16: bs_d1 used _safe(K, 1e-12) so log(S/K) misbehaved for S<0. Now an
       explicit ValueError on S<=0 or K<=0.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.services.greeks import (  # noqa: E402
    DAYS_PER_YEAR, RHO_BPS, VEGA_VOL_PT, aggregate_book, bs_call_price,
    bs_delta_call, bs_gamma, bs_rho_call, bs_rho_put, bs_theta_call,
    bs_theta_put, bs_vega, position_greeks,
)
from showme.engine.functions.derivative.ovme import _bs_price  # noqa: E402


# ------------------- C6: greek units match across paths -------------------


def test_vega_matches_ovme_path() -> None:
    """Same option priced two ways — vega must match (both per 1% vol)."""
    S, K, T, r, sigma, q = 100.0, 100.0, 0.25, 0.045, 0.20, 0.0
    via_service = bs_vega(S, K, sigma, T, r, q)
    via_ovme = _bs_price(S, K, T, r, sigma, q, True)["vega"]
    assert via_service == pytest.approx(via_ovme, rel=1e-9)


def test_theta_matches_ovme_path() -> None:
    """Theta call — both /365."""
    S, K, T, r, sigma, q = 100.0, 100.0, 0.25, 0.045, 0.20, 0.0
    via_service = bs_theta_call(S, K, sigma, T, r, q)
    via_ovme = _bs_price(S, K, T, r, sigma, q, True)["theta"]
    assert via_service == pytest.approx(via_ovme, rel=1e-9)


def test_rho_call_units_per_bp() -> None:
    """Rho should now be per 1 bp rate move (i.e. /10000)."""
    S, K, T, r, sigma = 100.0, 100.0, 1.0, 0.045, 0.20
    rho = bs_rho_call(S, K, sigma, T, r)
    # K*T*e^(-rT)*N(d2) at ATM ~ 100*1*0.956*0.5 ~ 47.8; /10000 => ~0.005
    assert 0.001 < rho < 0.01, f"rho_call per-bp out of range: {rho}"


# ------------------- C1: portfolio book scale -------------------


def test_position_greeks_book_aggregation_realistic_dollars() -> None:
    """One long ATM call, 1 contract * 100 shares. Greeks must be in
    "dollars per 1% vol", not per 1.00 vol (100x off)."""
    pos = {"kind": "call", "spot": 100, "strike": 100, "vol": 0.20,
           "T": 0.25, "r": 0.045, "q": 0.0,
           "quantity": 1, "contract_size": 100}
    g = position_greeks(pos)
    # Per-share vega at ATM, 25%T, 20% vol ~ 19.72 raw; /100 = 0.1972;
    # x100 contract = ~$19.72. Old broken code gave $1972.
    assert 10 < g["vega"] < 30, f"vega out of expected $-per-1% range: {g['vega']}"
    # Theta per day ~ -0.0273 /share * 100 = ~-$2.73. Was ~$0.0273 if
    # double-divided.
    assert -10 < g["theta"] < -0.5, f"theta per-day out of range: {g['theta']}"
    # Rho per-bp ~ K*T*N(d2)/10000 * 100 = ~$0.50 not $5000.
    assert 0 < g["rho"] < 5, f"rho per-bp out of range: {g['rho']}"


def test_aggregate_book_emits_units_dict() -> None:
    pos = {"kind": "call", "spot": 100, "strike": 100,
           "vol": 0.20, "T": 0.25, "quantity": 1, "contract_size": 100}
    agg = aggregate_book([pos])
    assert "units" in agg
    assert "1%" in agg["units"]["vega"]
    assert "day" in agg["units"]["theta"]
    assert "bp" in agg["units"]["rho"]


# ------------------- C3: vol=0 no longer ZeroDivisionError -------------------


def test_vol_zero_does_not_crash() -> None:
    """vol=0 used to ZeroDivisionError; now clamps to 1e-9 so callers
    can compute degenerate greeks without crashing. Math still gives
    zero gamma for vol≈0 (no time-value -> no convexity) but the
    function returns instead of dying."""
    # Should not raise.
    g = bs_gamma(100, 100, 0.0, 0.25)
    assert math.isfinite(g)  # finite, non-NaN
    # Vega/delta should also be defined without raising.
    v = bs_vega(100, 100, 0.0, 0.25)
    assert math.isfinite(v)


# ------------------- C10: assumptions_used field -------------------


def test_missing_vol_reports_assumption() -> None:
    pos = {"kind": "call", "spot": 100, "strike": 100,
           "quantity": 1, "contract_size": 100}  # no vol, no T
    g = position_greeks(pos)
    assert "assumptions_used" in g
    joined = " ".join(g["assumptions_used"])
    assert "vol=default" in joined and "T=default" in joined


def test_aggregate_book_collates_assumptions() -> None:
    positions = [
        {"symbol": "AAPL", "kind": "call", "spot": 200, "strike": 210,
         "quantity": 5, "contract_size": 100},  # missing vol, T
        {"symbol": "MSFT", "kind": "put", "spot": 400, "strike": 380,
         "vol": 0.30, "T": 30 / 365,
         "quantity": 3, "contract_size": 100},  # complete
    ]
    agg = aggregate_book(positions)
    assert "assumptions_used" in agg
    assert any("AAPL" in s for s in agg["assumptions_used"])


# ------------------- C16: S<=0 / K<=0 explicit reject -------------------


def test_S_zero_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        bs_call_price(0.0, 100, 0.2, 0.25)


def test_K_negative_raises() -> None:
    with pytest.raises(ValueError, match="positive"):
        bs_delta_call(100, -1.0, 0.2, 0.25)


# ------------------- Sanity: scale constants documented -------------------


def test_scale_constants_documented() -> None:
    assert VEGA_VOL_PT == 100.0
    assert RHO_BPS == 10_000.0
    assert DAYS_PER_YEAR == 365.0
