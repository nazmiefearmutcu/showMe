"""The DCF manifest output contract must describe the FCFE payload (DCF#3).

The handler is a two-stage FCFE model: it returns fair_value_per_share,
equity_value, rows and bridge. The manifest used to promise
intrinsic_value_per_share, enterprise_value, projection and assumptions,
which the payload never carried. The provider is faked; no network is used.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.equity.dcf import DCFFunction
from showme.manifest import REGISTRY, load_seeds

AAPL = Instrument(symbol="AAPL", asset_class=AssetClass.EQUITY)


class _Yf:
    def __init__(self, raw: dict) -> None:
        self._raw = raw

    async def fetch(self, request):
        return SimpleNamespace(extras={"raw": self._raw}, shares_outstanding=1.0e9)


def _run(raw: dict):
    deps = FunctionDeps(yfinance=_Yf(raw))
    return asyncio.run(DCFFunction(deps).execute(AAPL, wacc=0.09, growth_high=0.05,
                                                 growth_terminal=0.02, years=5))


def _spec():
    load_seeds()
    return REGISTRY.get("DCF")


def test_must_have_keys_are_present_in_the_ok_payload() -> None:
    res = _run({"freeCashflow": 1.0e10})
    assert res.data["status"] == "ok"
    missing = [k for k in _spec().output_contract.must_have if k not in res.data]
    assert missing == [], missing


def test_must_have_keys_are_present_in_the_needs_input_payload() -> None:
    res = _run({})
    assert res.data["status"] == "needs_input"
    missing = [k for k in _spec().output_contract.must_have if k not in res.data]
    assert missing == [], missing


def test_table_columns_name_the_row_keys() -> None:
    res = _run({"freeCashflow": 1.0e10})
    row_keys = set(res.data["rows"][0])
    columns = {c.key for c in _spec().table_schema.columns}
    assert columns <= row_keys, columns - row_keys


def test_must_have_keys_are_present_in_the_wacc_below_growth_payload() -> None:
    """DCF#3 review: the wacc <= terminal growth branch must carry the full
    must_have shape and an explicit status, not only error + assumptions."""
    deps = FunctionDeps(yfinance=_Yf({"freeCashflow": 1.0e10}))
    res = asyncio.run(DCFFunction(deps).execute(AAPL, wacc=0.02, growth_high=0.05,
                                                growth_terminal=0.025, years=5))
    assert res.data.get("status") == "input_error"
    assert res.data.get("reason")
    assert res.data.get("next_actions")
    missing = [k for k in _spec().output_contract.must_have if k not in res.data]
    assert missing == [], missing
    assert res.data["discount_rate"] == 0.02
    assert res.data["g_terminal"] == 0.025
    assert res.data["fair_value_per_share"] is None
    assert res.data["equity_value"] is None
