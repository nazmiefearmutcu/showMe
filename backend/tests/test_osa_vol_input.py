"""OSA: a non-numeric or non-finite leg vol is an input gap, not an exception.

Before the fix ``float(vol)`` ran outside any try block, so a text vol raised
instead of returning ``needs_input``; a NaN vol was priced as if real.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.derivative._stubs import OSAFunction


class _StubDeps:
    yfinance = None
    fred = None


def _run_osa(**params):
    osa = OSAFunction.__new__(OSAFunction)
    osa.deps = _StubDeps()
    return asyncio.run(osa.execute(**params))


def _leg(vol):
    return {"qty": 1, "strike": 100, "type": "CALL", "expiry": 0.25, "vol": vol}


@pytest.mark.parametrize("vol", ["abc", float("nan"), float("inf"), True])
def test_bad_vol_returns_needs_input(vol) -> None:
    res = _run_osa(spot=100, legs=[_leg(vol)])
    assert res.data["status"] == "needs_input"
    assert not res.data.get("curve")
    assert res.data["reason"]


def test_numeric_vol_still_prices() -> None:
    res = _run_osa(spot=100, legs=[_leg(0.25)])
    assert res.data["status"] == "ok"
    assert res.data["legs"][0]["vol"] == 0.25
