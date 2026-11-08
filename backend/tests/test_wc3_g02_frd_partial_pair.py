"""FRD#2-RQ: a partial pair (base or quote alone) never silently prices EURUSD.

Regression guard for the follow-up finding. At HEAD the strict pair rule returns
an explicit input_error for base-only and quote-only inputs, with no forward and
no pair; these tests pin that, including with a symbol present.
"""
from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.fx._funcs import FRDFunction


def _run(**params):
    return asyncio.run(FRDFunction().execute(None, live=False, spot=1.25, r_base=0.02, r_quote=0.05, **params))


@pytest.mark.parametrize(
    "params",
    [
        {"base": "GBP"},
        {"quote": "JPY"},
        {"base": "GBP", "symbol": "EURUSD"},
        {"quote": "JPY", "symbol": "EURUSD"},
    ],
)
def test_partial_pair_returns_explicit_state_and_never_eurusd(params) -> None:
    res = _run(**params)
    assert res.data["status"] in {"input_error", "needs_input"}
    assert res.data["pair"] is None
    assert res.data["rows"] == []
    assert "EURUSD" not in str(res.data.get("pair"))
    assert res.warnings and "No default pair is assumed" in res.warnings[0]


def test_full_base_and_quote_still_price_their_own_pair() -> None:
    res = _run(base="GBP", quote="USD")
    assert res.data.get("status") is None
    assert res.data["pair"] == "GBPUSD"
    assert res.data["base"] == "GBP" and res.data["quote"] == "USD"
