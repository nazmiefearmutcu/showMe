"""GREEKS rate units are explicit (p2a-g11).

A typed 0.5 meant 0.5 percent to the user but was priced as a 50 percent
decimal rate with no warning. Plain rates in (0.2, 1] are now refused with a
request for an explicit unit; rate_pct / rate_bps are unambiguous inputs.
"""
from __future__ import annotations

import asyncio
from datetime import date, timedelta

import pytest

from showme.engine.functions.portfolio.greeks import GREEKSFunction


class _Deps:
    yfinance = None


BASE = {
    "symbol": "AAPL", "kind": "put", "quantity": 1, "strike": 240.0,
    "expiry": (date.today() + timedelta(days=182)).isoformat(),
    "spot": 250.0, "vol": 0.25,
}


def _run(**position):
    return asyncio.run(GREEKSFunction(_Deps()).execute(positions=[{**BASE, **position}]))


def test_plain_rate_between_point_two_and_one_is_refused():
    res = _run(r=0.5)
    assert res.data["status"] == "input_error"
    assert "ambiguous" in res.data["reason"]
    assert "rate_pct=0.5" in res.data["reason"]


def test_plain_decimal_rate_is_labelled_as_decimal():
    res = _run(r=0.05)
    row = res.data["positions"][0]
    assert row["rate_source"] == "input_decimal"
    assert row["rate"] == pytest.approx(0.05)


def test_rate_pct_is_an_explicit_percent():
    row = _run(rate_pct=0.5).data["positions"][0]
    assert row["rate"] == pytest.approx(0.005)
    assert row["rate_source"] == "input_percent"


def test_rate_bps_is_an_explicit_basis_point_count():
    row = _run(rate_bps=50).data["positions"][0]
    assert row["rate"] == pytest.approx(0.005)
    assert row["rate_source"] == "input_bps"


def test_rate_pct_and_decimal_together_is_an_input_error():
    res = _run(rate_pct=0.5, r=0.005)
    assert res.data["status"] == "input_error"
    assert "rate" in res.data["reason"]


def test_percent_above_one_is_unchanged():
    row = _run(r=4.5).data["positions"][0]
    assert row["rate"] == pytest.approx(0.045)
    assert row["rate_source"] == "input_percent"
