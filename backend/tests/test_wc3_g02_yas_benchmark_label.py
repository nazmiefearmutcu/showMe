"""YAS#2: the benchmark the spread is measured against is named, never implied.

Named UST tenors select their FRED CMT series, the default is the 10Y and says
so, a non-US benchmark reports no spread, and a typed rate is labelled custom.
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.bond.yas import YASFunction

CMT = {"DGS2": 3.62, "DGS10": 4.11}


class _FRED:
    api_key = "test"

    def __init__(self):
        self.calls = []

    async def series(self, series_id, frequency="d"):
        self.calls.append(series_id)
        if series_id not in CMT:
            raise RuntimeError("down")
        idx = pd.to_datetime(["2026-11-05", "2026-11-06"])
        return pd.DataFrame({"value": [CMT[series_id] - 0.01, CMT[series_id]]}, index=idx)


def _run(symbol, **params):
    deps = FunctionDeps()
    deps.fred = _FRED()
    return asyncio.run(
        YASFunction(deps).execute(instrument=Instrument(symbol=symbol, asset_class=AssetClass.BOND), **params)
    )


def test_default_benchmark_is_the_ten_year_and_says_it_is_the_default() -> None:
    s = _run("US2Y").data["summary"]
    assert s["benchmark_series"] == "DGS10"
    assert "default" in s["benchmark_label"] and "DGS10" in s["benchmark_label"]


def test_named_ust2y_benchmark_uses_dgs2_and_is_labelled() -> None:
    res = _run("US10Y", benchmark="UST2Y")
    s = res.data["summary"]
    assert s["benchmark_series"] == "DGS2"
    assert "DGS2" in s["benchmark_label"] and "UST2Y" in s["benchmark_label"]
    assert s["benchmark_rate"] == pytest.approx(0.0362)
    assert s["spread_bps"] == pytest.approx((0.0411 - 0.0362) * 10_000)


def test_non_us_benchmark_reports_no_spread_and_says_no_live_series() -> None:
    s = _run("XS1234567890", price=99.0, coupon=4.0, years_to_maturity=5, benchmark="DBR10Y").data["summary"]
    assert s["spread_vs_benchmark"] is None
    assert s["benchmark_series"] is None
    assert "no live series" in s["benchmark_label"]


def test_typed_benchmark_rate_is_labelled_custom() -> None:
    s = _run("XS1234567890", price=99.0, coupon=4.0, years_to_maturity=5, benchmark=4.0).data["summary"]
    assert s["benchmark_label"] == "custom rate"
    assert s["benchmark_series"] is None
