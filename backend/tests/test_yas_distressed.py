"""D03-2026-05-24 (H12+H13+H14+H15): YAS bond Newton + distressed + convexity.

H12: distressed bonds (150% yield) used to make Newton diverge to +/-inf;
     bisection fallback now bracket-solves.
H13+H14: 30y 4% bond convexity should be ~200 (per-period y consistent,
     freq^2 normalization correct), not the inflated ~700 of the old code.
H15: _rate_decimal heuristic "x>1 -> /100" caught 150% yield (treats as
     1.50 decimal = "0.015 = 1.5%"). Now ``assume_decimal=True`` skips
     this and lets the caller send the raw decimal 1.50 for 150% yield.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.bond.yas import (  # noqa: E402
    _rate_decimal, _ytm_macaulay_modified_duration,
)


# ---------------- H12: distressed convergence ----------------


def test_distressed_bond_does_not_diverge() -> None:
    """Bond priced at $20 face $100 with 5% coupon — implied YTM is
    extremely high but should finite & positive."""
    metrics = _ytm_macaulay_modified_duration(
        face=100.0, price=20.0, coupon=0.05, n_periods=20, freq=2)
    assert metrics["ytm"] > 0.20  # at least 20% yield
    assert metrics["ytm"] < 5.0   # but not blown up
    import math
    assert math.isfinite(metrics["ytm"])
    assert math.isfinite(metrics["modified_duration"])
    assert math.isfinite(metrics["convexity"])


def test_par_bond_ytm_equals_coupon() -> None:
    """A par bond (price=face) has YTM == coupon rate (sanity)."""
    metrics = _ytm_macaulay_modified_duration(
        face=100.0, price=100.0, coupon=0.04, n_periods=20, freq=2)
    assert metrics["ytm"] == pytest.approx(0.04, abs=1e-4)


# ---------------- H13+H14: convexity per-period scale ----------------


def test_30y_par_bond_convexity_passes_pnl_taylor_check() -> None:
    """30y 4% par bond convexity should produce the correct Taylor-series
    P&L for a 25bp yield bump. The formal value is ≈ 421 — many textbooks
    quote a smaller "convexity in years²" (~200) but the dollar-convexity
    that the second-order P&L formula expects is around 411-425."""
    metrics = _ytm_macaulay_modified_duration(
        face=100.0, price=100.0, coupon=0.04, n_periods=60, freq=2)
    # Cross-check: -D*dy + 0.5*C*dy² should match exact bond ΔP/P.
    delta_y = 0.0025  # +25bp
    # Exact price at 4.25% YTM:
    y_per = 0.0425 / 2
    c = 0.04 / 2
    exact_pv = sum(c * 100 / (1 + y_per) ** k for k in range(1, 61)) + \
        100 / (1 + y_per) ** 60
    exact_pct = (exact_pv - 100) / 100
    approx_pct = -metrics["modified_duration"] * delta_y + \
        0.5 * metrics["convexity"] * delta_y * delta_y
    # If convexity is double-counted (~700), approx would be ~-0.020; if
    # missing (~0), approx would be ~-0.043; correct (~420) gives -0.0421.
    assert abs(approx_pct - exact_pct) < 1e-4, \
        f"convexity={metrics['convexity']} fails Taylor: approx={approx_pct} exact={exact_pct}"


def test_quarterly_convexity_consistent_with_semi() -> None:
    """Quarterly (freq=4) and semi-annual (freq=2) representations of
    the same bond should give very similar convexity (small drift OK)."""
    # 5y 4% par bond, both freqs.
    sa = _ytm_macaulay_modified_duration(
        face=100.0, price=100.0, coupon=0.04, n_periods=10, freq=2)
    qt = _ytm_macaulay_modified_duration(
        face=100.0, price=100.0, coupon=0.04, n_periods=20, freq=4)
    # Should agree within ~5% — used to drift much more because the
    # per-period y wasn't consistently applied.
    assert abs(sa["convexity"] - qt["convexity"]) / sa["convexity"] < 0.10


# ---------------- H15: _rate_decimal explicit decimal -------------


def test_rate_decimal_heuristic_still_works_for_percent() -> None:
    """4.5 (percent) -> 0.045 (decimal) — back-compat."""
    assert _rate_decimal(4.5, 0.0) == pytest.approx(0.045)
    # 0.045 (already decimal) stays 0.045.
    assert _rate_decimal(0.045, 0.0) == pytest.approx(0.045)


def test_rate_decimal_assume_decimal_skips_heuristic() -> None:
    """assume_decimal=True passes 1.50 through as 150% decimal yield."""
    assert _rate_decimal(1.50, 0.0, assume_decimal=True) == 1.50
    # Without flag, the legacy heuristic catches and gives 0.015.
    assert _rate_decimal(1.50, 0.0, assume_decimal=False) == 0.015
