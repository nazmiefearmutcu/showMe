"""OSA rate and dividend-yield inputs are parsed honestly, never raised.

A non-numeric or non-finite ``rate`` / ``div_yield`` is an input gap
(``needs_input`` with a reason), not an unhandled exception. A missing or
null value takes the documented default and says so in ``rate_source`` /
``div_yield_source``, so the output never hides where the number came from.
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


CALL_SPREAD = [
    {"qty": 1, "strike": 100, "type": "CALL", "expiry": 0.25, "vol": 0.25},
    {"qty": -1, "strike": 110, "type": "CALL", "expiry": 0.25, "vol": 0.25},
]


@pytest.mark.parametrize("bad", ["abc", "nan", "inf", "-inf", ["0.04"], {"r": 0.04}])
def test_invalid_rate_is_an_input_gap_not_an_exception(bad) -> None:
    # RED before fix: float("abc") raised ValueError out of execute().
    res = _run_osa(spot=100, legs=CALL_SPREAD, rate=bad)
    assert res.data["status"] == "needs_input"
    assert "rate" in res.data["reason"].lower()
    assert not res.data.get("curve")


@pytest.mark.parametrize("bad", ["x", "nan", True])
def test_invalid_div_yield_is_an_input_gap_not_an_exception(bad) -> None:
    res = _run_osa(spot=100, legs=CALL_SPREAD, div_yield=bad)
    assert res.data["status"] == "needs_input"
    assert "div_yield" in res.data["reason"].lower() or "dividend" in res.data["reason"].lower()
    assert not res.data.get("curve")


def test_null_rate_takes_the_default_and_reports_it() -> None:
    res = _run_osa(spot=100, legs=CALL_SPREAD, rate=None)
    assert res.data["status"] == "ok"
    assert res.data["rate"] == 0.045
    assert res.data["rate_source"] == "default"


def test_entered_rate_reports_param_source() -> None:
    res = _run_osa(spot=100, legs=CALL_SPREAD, rate="0.05")
    assert res.data["status"] == "ok"
    assert res.data["rate"] == 0.05
    assert res.data["rate_source"] == "param"


def test_null_div_yield_defaults_to_zero_and_reports_it() -> None:
    res = _run_osa(spot=100, legs=CALL_SPREAD, div_yield=None)
    assert res.data["status"] == "ok"
    assert res.data["div_yield"] == 0.0
    assert res.data["div_yield_source"] == "default"


def test_entered_div_yield_reports_param_source() -> None:
    res = _run_osa(spot=100, legs=CALL_SPREAD, div_yield=0.015)
    assert res.data["div_yield"] == 0.015
    assert res.data["div_yield_source"] == "param"
