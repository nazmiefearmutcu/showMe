"""P1a-g03 OSA#1 — multi-expiry strategies must be valued on one time basis.

A calendar (short 10-day call, long 91-day call, same strike) used to be
valued as if every leg expired at the longest expiry, with intrinsic value
only. The two same-strike calls then cancelled to zero and the P&L curve was
flat at minus the whole debit. The fixed engine evaluates the position at the
first expiry: expiring legs at intrinsic, longer legs at Black-Scholes value
with their remaining time.
"""

from __future__ import annotations

import asyncio
import math

import pytest

from showme.engine.functions.derivative._stubs import OSAFunction
from showme.engine.functions.derivative.ovme import _bs_price


class _StubDeps:
    yfinance = None
    fred = None


def _run(**params):
    osa = OSAFunction.__new__(OSAFunction)
    osa.deps = _StubDeps()
    return asyncio.run(osa.execute(**params))


CALENDAR_LEGS = [
    {"qty": -1, "strike": 735, "type": "CALL", "expiry": 10 / 365, "vol": 0.25},
    {"qty": 1, "strike": 735, "type": "CALL", "expiry": 91 / 365, "vol": 0.25},
]


def _nearest(curve, spot: float):
    return min(curve, key=lambda row: abs(row["spot"] - spot))


def test_calendar_pnl_is_not_flat_at_minus_debit() -> None:
    res = _run(spot=735.29, rate=0.045, legs=CALENDAR_LEGS)
    pnls = [row["pnl"] for row in res.data["curve"]]
    # RED before fix: every pnl equal to -net_debit * exp(r*T_long).
    assert max(pnls) - min(pnls) > 1.0, "calendar P&L must vary with spot"


def test_calendar_is_profitable_near_strike_at_short_expiry() -> None:
    res = _run(spot=735.29, rate=0.045, legs=CALENDAR_LEGS)
    at_strike = _nearest(res.data["curve"], 735.0)
    # Long 81-day call still carries time value at the short expiry, so the
    # calendar is worth more than its debit near the strike (BSM ~ +10).
    assert at_strike["pnl"] > 0.0
    assert res.data["summary"]["breakeven_count_visible"] >= 1


def test_calendar_pnl_matches_bsm_at_first_expiry() -> None:
    res = _run(spot=735.29, rate=0.045, legs=CALENDAR_LEGS)
    horizon = 10 / 365
    rate = 0.045
    net_debit = res.data["summary"]["net_debit"]
    row = _nearest(res.data["curve"], 735.0)
    s = row["spot"]
    # Short 10-day call expires at the horizon (intrinsic only); the long
    # 91-day call is marked at Black-Scholes with its remaining 81 days.
    short_value = -1 * max(s - 735, 0.0)
    long_value = _bs_price(s, 735, 91 / 365 - horizon, rate, 0.25, 0.0, True)["price"]
    expected = short_value + long_value - net_debit * math.exp(rate * horizon)
    assert row["pnl"] == pytest.approx(expected, rel=1e-6)
    assert res.data["summary"]["evaluation_horizon_years"] == pytest.approx(horizon)


def test_single_expiry_strategy_unchanged_intrinsic_at_expiry() -> None:
    legs = [
        {"qty": 1, "strike": 100, "type": "CALL", "expiry": 0.5, "vol": 0.3},
        {"qty": -1, "strike": 110, "type": "CALL", "expiry": 0.5, "vol": 0.3},
    ]
    res = _run(spot=100, rate=0.05, legs=legs)
    row = _nearest(res.data["curve"], 120.0)
    # Both legs expire together: payoff is the plain call spread payoff.
    assert row["payoff"] == pytest.approx(min(max(row["spot"] - 100, 0), 10), abs=1e-9)
    assert row["fv_debit"] == pytest.approx(row["net_debit"] * math.exp(0.05 * 0.5), rel=1e-9)
