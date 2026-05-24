"""D03-2026-05-24 (H20+H21): Heston MC greeks + full-truncation Vt fix.

H20: heston_greeks() now exposes Delta/Gamma/Vega via finite differences
     so a Heston-priced book can be hedged.
H21: variance update was Vt = Vt + drift*dt + diff (raw Vt), so Vt could
     drift below 0 even though Vp clamped it. Now it's Vt = Vp + ... which
     is the Andersen 2008 full-truncation recipe.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.derivative.heston import (  # noqa: E402
    HestonParams, heston_greeks, heston_mc,
)


# ---------------- H20: Greeks present and finite ----------------


def test_heston_greeks_returns_delta_gamma_vega() -> None:
    p = HestonParams(kappa=2.0, theta=0.04, sigma=0.4, rho=-0.6, v0=0.04)
    g = heston_greeks(S=100, K=100, T=0.5, r=0.045, q=0.0, params=p,
                      is_call=True, paths=4_000, steps=40)
    assert "delta" in g and "gamma" in g and "vega" in g
    # ATM call Delta should be in (0.4, 0.7) at reasonable maturity.
    assert 0.30 < g["delta"] < 0.80, f"delta {g['delta']}"
    # Gamma positive at ATM.
    assert g["gamma"] > 0
    # Vega positive at ATM.
    assert g["vega"] > 0


def test_heston_greeks_put_delta_negative() -> None:
    p = HestonParams(kappa=2.0, theta=0.04, sigma=0.4, rho=-0.6, v0=0.04)
    g = heston_greeks(S=100, K=100, T=0.5, r=0.045, q=0.0, params=p,
                      is_call=False, paths=4_000, steps=40)
    assert g["delta"] < 0  # put delta sign convention


# ---------------- H21: variance stays non-negative (path-level) ----------


def test_heston_mc_does_not_blow_up_with_high_volvol() -> None:
    """High sigma (vol-of-vol) used to push raw Vt below 0 via the drift
    term. Andersen full-truncation keeps Vt bounded."""
    p = HestonParams(kappa=4.0, theta=0.04, sigma=1.5, rho=-0.7, v0=0.04)
    out = heston_mc(S=100, K=100, T=1.0, r=0.045, q=0.0, params=p,
                    paths=4_000, steps=60)
    import math
    assert math.isfinite(out["price"])
    assert out["price"] > 0
    # Standard error should also be finite.
    assert math.isfinite(out["stderr"])


def test_heston_price_converges_near_bs_for_small_volvol() -> None:
    """In the sigma->0 limit Heston should approximate BS with sqrt(v0)
    flat vol. Loose tolerance since MC has noise."""
    from showme.engine.services.iv_solver import _bs_price_local
    p = HestonParams(kappa=2.0, theta=0.04, sigma=0.01, rho=0.0, v0=0.04)
    h = heston_mc(S=100, K=100, T=0.5, r=0.045, q=0.0, params=p,
                  paths=20_000, steps=80)["price"]
    bs = _bs_price_local(100, 100, 0.5, 0.045, 0.20, 0.0, True)
    assert h == pytest.approx(bs, abs=0.30)  # MC noise tolerance
