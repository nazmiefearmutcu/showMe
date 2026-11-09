"""YAS prices are quoted per 100 of face; cashflows are scaled by face.

Regression for P1a-g12 finding YAS#1: the solver discounted face-scaled
cashflows against a per-100 price, so face=1000 with price 99.5 produced a
48.5% YTM instead of 4.31%. The price must be scaled to face before solving.
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.bond.yas import YASFunction

CMT = {"DGS10": 4.11, "DGS2": 3.62}


class _FRED:
    api_key = "test"

    def __init__(self, table=CMT):
        self.table = table

    async def series(self, series_id, frequency="d"):
        if series_id not in self.table:
            raise RuntimeError("down")
        idx = pd.to_datetime(["2026-11-05", "2026-11-06"])
        return pd.DataFrame({"value": [self.table[series_id] - 0.01, self.table[series_id]]}, index=idx)


def _run(**params):
    deps = FunctionDeps()
    deps.fred = _FRED()
    fn = YASFunction(deps)
    symbol = params.pop("symbol", "XS1234567890")
    instrument = Instrument(symbol=symbol, asset_class=AssetClass.BOND)
    return asyncio.run(fn.execute(instrument=instrument, **params))


def _ytm(res) -> float:
    return {r["metric"]: r["value"] for r in res.data["rows"]}["yield_to_maturity"]


def test_price_per_100_is_independent_of_face():
    # Same bond quoted per 100: face must not change the yield.
    at_100 = _run(face=100.0, price=99.5, coupon=0.0425, years_to_maturity=10, frequency=2)
    at_1000 = _run(face=1000.0, price=99.5, coupon=0.0425, years_to_maturity=10, frequency=2)
    assert _ytm(at_1000) == pytest.approx(_ytm(at_100), abs=1e-9)


def test_face_1000_at_99_5_matches_the_known_yield():
    res = _run(face=1000.0, price=99.5, coupon=0.0425, years_to_maturity=10, frequency=2)
    # Independent value: 10y semi-annual 4.25% bond priced at 99.5 per 100 -> 4.3121%.
    assert _ytm(res) == pytest.approx(0.04312082, abs=1e-6)
    assert res.data["summary"]["ytm_pct"] == pytest.approx(4.312082, abs=1e-4)


def test_generic_treasury_with_face_1000_is_still_a_par_bond():
    # Par bond at the CMT yield: the quote is 100 per 100 face, not 1000.
    deps = FunctionDeps()
    deps.fred = _FRED()
    res = asyncio.run(YASFunction(deps).execute(
        instrument=Instrument(symbol="US10Y", asset_class=AssetClass.BOND), face=1000.0))
    assert res.data["summary"]["price"] == pytest.approx(100.0)
    assert res.data["summary"]["ytm"] == pytest.approx(0.0411, abs=1e-9)


def test_single_cashflow_bill_scales_price_by_face():
    at_100 = _run(symbol="XS1BILL", face=100.0, price=98.0, coupon=0.0, years_to_maturity=0.25, frequency=2)
    at_1000 = _run(symbol="XS1BILL", face=1000.0, price=98.0, coupon=0.0, years_to_maturity=0.25, frequency=2)
    assert _ytm(at_1000) == pytest.approx(_ytm(at_100), abs=1e-9)
