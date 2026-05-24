"""D03-2026-05-24 (H9): hybrid IV solver — Newton + bisection.

Pin:
- ATM round-trip: BS(sigma)->price->IV->sigma
- ITM/OTM round-trip
- Deep ITM (intrinsic only)
- Expired (T<=0)
- Negative market_price (below intrinsic): graceful degrade
- Newton divergence path lands on bisection
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

from showme.engine.services.iv_solver import (  # noqa: E402
    _bs_price_local, implied_vol,
)


def _atm_call_price(S: float, T: float, sigma: float, r: float = 0.045,
                    q: float = 0.0) -> float:
    return _bs_price_local(S, S, T, r, sigma, q, True)


# ---------------- Newton ATM round-trip ----------------


def test_atm_round_trip_call() -> None:
    sigma = 0.20
    price = _atm_call_price(100, 0.25, sigma)
    res = implied_vol(market_price=price, S=100, K=100, T=0.25, r=0.045,
                      is_call=True)
    assert res["converged"]
    assert res["iv"] == pytest.approx(sigma, abs=1e-4)
    assert res["method"] == "newton"


def test_atm_round_trip_put() -> None:
    sigma = 0.35
    p = _bs_price_local(100, 100, 0.5, 0.045, sigma, 0.0, False)
    res = implied_vol(market_price=p, S=100, K=100, T=0.5, r=0.045,
                      is_call=False)
    assert res["converged"]
    assert res["iv"] == pytest.approx(sigma, abs=1e-4)


# ---------------- ITM / OTM ----------------


def test_itm_call() -> None:
    """Deep ITM call: S=120, K=100, vol=0.25."""
    sigma_true = 0.25
    price = _bs_price_local(120, 100, 0.5, 0.045, sigma_true, 0.0, True)
    res = implied_vol(market_price=price, S=120, K=100, T=0.5, r=0.045,
                      is_call=True)
    assert res["converged"]
    assert res["iv"] == pytest.approx(sigma_true, abs=1e-3)


def test_otm_put() -> None:
    """OTM put: S=100, K=85, vol=0.40."""
    sigma_true = 0.40
    price = _bs_price_local(100, 85, 0.25, 0.045, sigma_true, 0.0, False)
    res = implied_vol(market_price=price, S=100, K=85, T=0.25, r=0.045,
                      is_call=False)
    assert res["converged"]
    assert res["iv"] == pytest.approx(sigma_true, abs=1e-3)


# ---------------- Intrinsic / degenerate ----------------


def test_deep_itm_at_intrinsic_returns_zero_vol() -> None:
    """Market = intrinsic means no time value — no positive vol solves it."""
    S, K = 150, 100
    intrinsic = S - K  # 50
    res = implied_vol(market_price=intrinsic, S=S, K=K, T=0.5, r=0.045,
                      is_call=True)
    assert res["method"] == "intrinsic"
    assert not res["converged"]
    assert res["iv"] == 0.0


def test_expired_option_returns_intrinsic_method() -> None:
    res = implied_vol(market_price=10.0, S=110, K=100, T=0.0, r=0.045,
                      is_call=True)
    assert res["method"] == "intrinsic"


def test_below_intrinsic_market_price_does_not_crash() -> None:
    """Market price below intrinsic is degenerate — return intrinsic."""
    res = implied_vol(market_price=1.0, S=200, K=100, T=0.5, r=0.045,
                      is_call=True)
    assert res["method"] == "intrinsic"


# ---------------- Bisection fallback path ----------------


def test_high_vol_solves_via_bisection_if_newton_overshoots() -> None:
    """Very-high IV (1.50) usually triggers Newton overshoot or vega
    collapse near the bounds — must still converge through bisection."""
    sigma_true = 1.50
    price = _bs_price_local(100, 100, 0.5, 0.045, sigma_true, 0.0, True)
    res = implied_vol(market_price=price, S=100, K=100, T=0.5, r=0.045,
                      is_call=True, sigma_low=0.01, sigma_high=5.0)
    assert res["converged"]
    assert res["iv"] == pytest.approx(sigma_true, abs=1e-3)


# ---------------- Reject invalid inputs ----------------


def test_negative_S_raises() -> None:
    with pytest.raises(ValueError):
        implied_vol(market_price=5.0, S=-100, K=100, T=0.25)


def test_zero_K_raises() -> None:
    with pytest.raises(ValueError):
        implied_vol(market_price=5.0, S=100, K=0.0, T=0.25)
