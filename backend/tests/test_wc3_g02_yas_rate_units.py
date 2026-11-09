"""XCON-2 (YAS part): a coupon or benchmark of 0.5 is not silently read as 50%.

yas._rate_decimal treats |x| > 1 as percent and anything else as decimal, so a
JGB-style coupon of 0.5 (meaning 0.5%) became a 50% coupon with no warning.
A value in the ambiguous band (0.2, 1] is now refused with an explicit
input_error unless the caller states the unit with assume_decimal.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.bond.yas import YASFunction

CMT = {"DGS10": 4.11}


class _FRED:
    api_key = "test"

    async def series(self, series_id, frequency="d"):
        if series_id not in CMT:
            raise RuntimeError("down")
        idx = pd.to_datetime(["2026-11-05", "2026-11-06"])
        return pd.DataFrame({"value": [CMT[series_id] - 0.01, CMT[series_id]]}, index=idx)


def _run(**params):
    deps = FunctionDeps()
    deps.fred = _FRED()
    bond = Instrument(symbol="XS1234567890", asset_class=AssetClass.BOND)
    return asyncio.run(YASFunction(deps).execute(instrument=bond, price=99.0, years_to_maturity=5, **params))


def test_half_percent_coupon_is_refused_not_read_as_fifty_percent() -> None:
    res = _run(coupon=0.5)
    assert res.data["status"] == "input_error"
    assert "coupon" in res.data["reason"].lower()
    assert res.data["rows"] == []


def test_half_percent_coupon_with_explicit_decimal_unit_is_priced() -> None:
    res = _run(coupon=0.005, assume_decimal=True)
    assert res.data.get("status") is None
    assert res.data["summary"]["coupon_rate"] == 0.005


def test_percent_coupon_above_one_is_still_read_as_percent() -> None:
    res = _run(coupon=4.25)
    assert res.data["summary"]["coupon_rate"] == 0.0425


def test_ambiguous_benchmark_is_refused_not_read_as_fifty_percent() -> None:
    res = _run(coupon=4.25, benchmark=0.5)
    assert res.data["status"] == "input_error"
    assert "benchmark" in res.data["reason"].lower()
