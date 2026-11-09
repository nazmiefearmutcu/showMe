"""GREEKS#1 follow-up: a plain decimal rate in (0, 0.2] is still priced as a decimal.

``r=0.1`` typed by a user who means 0.1 percent is read as 10 percent. That
reading is allowed (``r=0.045`` is the normal decimal form), but it must not be
silent: the response carries a warning naming the percent it priced, and the row
keeps ``rate_source=input_decimal``.
"""

from __future__ import annotations

import asyncio
from datetime import date, timedelta

from showme.engine.functions.portfolio.greeks import GREEKSFunction

BASE = {
    "symbol": "AAPL", "kind": "put", "quantity": 1, "strike": 240.0,
    "expiry": (date.today() + timedelta(days=182)).isoformat(),
    "spot": 250.0, "vol": 0.25,
}


class _Deps:
    yfinance = None


def _run(**position):
    return asyncio.run(GREEKSFunction(_Deps()).execute(positions=[{**BASE, **position}]))


def test_plain_decimal_rate_produces_a_warning_naming_the_percent_priced() -> None:
    res = _run(r=0.1)
    assert res.data["positions"][0]["rate_source"] == "input_decimal"
    warnings = " ".join(res.warnings)
    assert "0.1" in warnings
    assert "10%" in warnings


def test_percent_rate_above_one_has_no_decimal_warning() -> None:
    res = _run(r=4.5)
    assert not any("decimal" in w for w in res.warnings)
