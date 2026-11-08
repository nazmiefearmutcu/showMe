"""WC2-G06 honesty regressions: OVME placeholder inputs, TAUC template horizon.

Each test reproduces a finding through the public handler with the network
patched out (no adapter is reachable here).
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.derivative.ovme import OVMEFunction


def _run_ovme(**params):
    fn = OVMEFunction()
    fn.deps = None
    return asyncio.run(fn.execute(**params))


def test_ovme_with_no_inputs_does_not_price_a_demo_option() -> None:
    res = _run_ovme()
    assert res.data["status"] == "needs_input"
    assert "price" not in res.data
    assert res.data["curve"] == []
    assert set(res.data["missing_inputs"]) == {"spot", "strike", "years_to_expiry", "vol"}


def test_ovme_missing_spot_is_not_filled_with_100() -> None:
    res = _run_ovme(strike=100, years_to_expiry=0.5, vol=0.25)
    assert res.data["status"] == "needs_input"
    assert res.data["missing_inputs"] == ["spot"]
    assert "price" not in res.data


def test_ovme_non_numeric_input_is_an_input_error_not_a_crash() -> None:
    res = _run_ovme(spot="abc", strike=100, years_to_expiry=0.5, vol=0.25)
    assert res.data["status"] == "input_error"
    assert any("spot" in w for w in res.warnings)
