"""D03-2026-05-24 (H17+H18+H19): OSA fixes — grid range, debit carry-forward,
per-leg IV solver.

H17: spot grid now derived from strike list, not hardcoded 50-150% of S.
     Low-priced underlyings (S=20) with wing strikes (e.g. 50) used to
     fall off the chart.
H18 (revised by HNT-03): initial net_debit is paid at t=0; expiry_payoff is
     at T. Compound the debit FORWARD (fv_debit = net_debit * exp(+r*T)) so
     they share the same future time basis. The old PV-discount version
     understated the cost by exp(-2rT).
H19: per-leg vol resolution — caller can pass ``market_price`` per leg
     and the function back-solves the implied vol.
"""

from __future__ import annotations

import asyncio
import math
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.derivative._stubs import OSAFunction  # noqa: E402
from showme.engine.functions.derivative.ovme import _bs_price  # noqa: E402


class _StubDeps:
    yfinance = None
    fred = None


def _run_osa(**params):
    osa = OSAFunction.__new__(OSAFunction)
    osa.deps = _StubDeps()
    return asyncio.run(osa.execute(**params))


# ---------------- H17: grid covers wing strikes ----------------


def test_grid_covers_wing_strikes_on_low_priced_underlying() -> None:
    """S=20 with strikes 10..50 — grid must span wing strikes."""
    res = _run_osa(
        spot=20,
        legs=[
            {"qty": 1, "strike": 10, "type": "CALL", "expiry": 0.25, "vol": 0.5},
            {"qty": -1, "strike": 50, "type": "CALL", "expiry": 0.25, "vol": 0.5},
        ],
    )
    curve = res.data["curve"]
    spots = [row["spot"] for row in curve]
    assert min(spots) <= 10  # min strike reached
    assert max(spots) >= 50  # max strike reached


# ---------------- H18 (HNT-03): debit compounded to expiry ----------------


def test_fv_debit_compound_at_long_maturity() -> None:
    """A long-dated debit spread should have curve.pnl reflect the debit
    carried forward to expiry (fv_debit), not raw net_debit."""
    legs = [
        {"qty": 1, "strike": 100, "type": "CALL", "expiry": 2.0, "vol": 0.25},
        {"qty": -1, "strike": 110, "type": "CALL", "expiry": 2.0, "vol": 0.25},
    ]
    res = _run_osa(spot=100, rate=0.05, legs=legs)
    curve = res.data["curve"]
    assert curve, "curve should be non-empty"
    row = curve[0]
    fv_debit = row["fv_debit"]
    net_debit = row["net_debit"]
    # 2-yr 5% carry factor ≈ exp(+0.10) = 1.105
    expected_factor = math.exp(0.05 * 2.0)
    assert fv_debit == pytest.approx(net_debit * expected_factor, rel=1e-6)
    # pnl must be payoff minus the FUTURE-value debit (HNT-03).
    assert row["pnl"] == pytest.approx(row["payoff"] - fv_debit, rel=1e-6)
    # The old PV key is gone.
    assert "pv_debit" not in row


# ---------------- H19: per-leg IV from market_price ----------------


def test_leg_market_price_back_solves_iv() -> None:
    """Caller passes leg market_price; OSA should solve IV."""
    # Build a leg whose "market" price matches BS at sigma=0.35.
    K = 105
    expiry = 0.5
    sigma_true = 0.35
    bs = _bs_price(100, K, expiry, 0.045, sigma_true, 0.0, True)
    market = bs["price"]
    res = _run_osa(
        spot=100, rate=0.045,
        legs=[{"qty": 1, "strike": K, "type": "CALL", "expiry": expiry,
               "market_price": market}],  # NO vol, force solve
    )
    legs = res.data["legs"]
    assert len(legs) == 1
    leg = legs[0]
    assert leg["vol"] == pytest.approx(sigma_true, abs=1e-3)
    assert leg["iv_source"].startswith("solved_")


# ---------------- Sanity: existing happy path unchanged ----------------


def test_default_call_spread_still_works() -> None:
    res = _run_osa()
    assert res.data["status"] == "ok"
    assert len(res.data["curve"]) == 101
