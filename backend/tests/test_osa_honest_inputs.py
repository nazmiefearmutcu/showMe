"""T10-OSA-placeholder_value — OSA must not invent spot, legs or vol.

The offline honesty audit called ``OSA`` with no parameters and got
``status=ok`` priced at a spot of 100 with a made-up call spread
(strikes 100/110, vol 0.25). Missing inputs must return an explicit
``needs_input`` state with a reason, never a priced placeholder.
"""

from __future__ import annotations

import asyncio

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


def test_no_parameters_returns_needs_input_not_a_priced_placeholder() -> None:
    res = _run_osa()
    # RED before fix: status == "ok" with a curve priced at spot 100.
    assert res.data["status"] == "needs_input"
    assert not res.data.get("curve")
    assert "reason" in res.data and res.data["reason"]


def test_missing_spot_is_not_filled_with_100() -> None:
    res = _run_osa(legs=CALL_SPREAD)
    # RED before fix: spot silently defaulted to 100 and the curve was priced.
    assert res.data["status"] == "needs_input"
    assert not res.data.get("curve")
    assert res.data.get("spot") is None


def test_missing_legs_is_not_filled_with_a_template_spread() -> None:
    res = _run_osa(spot=100)
    # RED before fix: a default 100/110 call spread was priced.
    assert res.data["status"] == "needs_input"
    assert not res.data.get("curve")


def test_leg_without_vol_or_market_price_needs_input() -> None:
    res = _run_osa(
        spot=100,
        legs=[{"qty": 1, "strike": 100, "type": "CALL", "expiry": 0.25}],
    )
    # RED before fix: the leg was priced at the 0.25 placeholder vol.
    assert res.data["status"] == "needs_input"
    assert not res.data.get("curve")
    assert "vol" in res.data["reason"].lower()


def test_explicit_inputs_still_price() -> None:
    res = _run_osa(spot=100, legs=CALL_SPREAD)
    assert res.data["status"] == "ok"
    assert len(res.data["curve"]) == 101
