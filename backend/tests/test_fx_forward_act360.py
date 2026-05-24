"""D03-2026-05-24 (H22): FX forward ACT/360 day-count convention."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
ENGINE = ROOT / "engine"
if str(ENGINE) not in sys.path:
    sys.path.insert(0, str(ENGINE))

from showme.engine.functions.fx._funcs import _forward  # noqa: E402


def test_default_uses_act360() -> None:
    """Default day_count='ACT/360' applies 365/360 factor."""
    spot = 1.0835  # EURUSD
    r_base = 0.035  # EUR
    r_quote = 0.045  # USD
    years = 0.25  # 3M
    fwd_360 = _forward(spot, r_base, r_quote, years, "ACT/360")
    fwd_365 = _forward(spot, r_base, r_quote, years, "ACT/365")
    # ACT/360 should produce slightly larger absolute differential.
    assert fwd_360 != fwd_365
    # Manual check: ACT/360 multiplies years by 365/360 ≈ 1.01389.
    years_360 = years * 365.0 / 360.0
    expected = spot * (1 + r_quote * years_360) / (1 + r_base * years_360)
    assert fwd_360 == pytest.approx(expected, rel=1e-12)


def test_act365_passthrough() -> None:
    """day_count='ACT/365' returns the legacy unscaled formula."""
    spot, r_base, r_quote, years = 1.0835, 0.035, 0.045, 0.5
    fwd = _forward(spot, r_base, r_quote, years, "ACT/365")
    expected = spot * (1 + r_quote * years) / (1 + r_base * years)
    assert fwd == pytest.approx(expected, rel=1e-12)


def test_zero_rate_differential_returns_spot() -> None:
    spot = 1.30
    assert _forward(spot, 0.02, 0.02, 0.25) == pytest.approx(spot, rel=1e-12)
