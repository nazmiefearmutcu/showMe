"""SRCH names its universe honestly: a sovereign curve screener, not a bond screener.

The universe is 25 benchmark curve points (sovereign and TIPS tenors), with no
CUSIPs, coupons or issue-level yields, so the registered name must not claim
an issue-level bond screen.
"""
from __future__ import annotations

from showme.engine.functions.screen._funcs import SRCHFunction


def test_srch_registered_name_describes_curve_universe() -> None:
    assert SRCHFunction.name == "Sovereign Curve Screener"
    assert "bond screener" not in SRCHFunction.name.lower()
