"""YAS analyses the bond it is asked about (strict truth audit 2026-11-07).

It used to ignore the symbol and price one static bond (price 99.5, coupon
4.25%, 10y) for US10Y and US2Y alike, with a static 4.45% benchmark.
"""
from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.bond.yas import YASFunction, generic_treasury

CMT = {"DGS2": 3.62, "DGS10": 4.11, "DGS30": 4.70}


class _FRED:
    api_key = "test"

    def __init__(self, table=CMT, fail=()):
        self.table, self.fail, self.calls = table, set(fail), []

    async def series(self, series_id, frequency="d"):
        self.calls.append(series_id)
        if series_id in self.fail or series_id not in self.table:
            raise RuntimeError("down")
        idx = pd.to_datetime(["2026-11-05", "2026-11-06"])
        return pd.DataFrame({"value": [self.table[series_id] - 0.01, self.table[series_id]]}, index=idx)


def _fn(fred):
    deps = FunctionDeps()
    deps.fred = fred
    return YASFunction(deps)


def _bond(sym):
    return Instrument(symbol=sym, asset_class=AssetClass.BOND)


def _run(fn, **params):
    return asyncio.run(fn.execute(**params))


@pytest.mark.parametrize("sym, series, years", [("US2Y", "DGS2", 2.0), ("US10Y", "DGS10", 10.0),
                                                 ("US3M", "DGS3MO", 0.25), ("US30Y", "DGS30", 30.0)])
def test_generic_tenor_mapping(sym, series, years):
    assert generic_treasury(sym) == (series, years)


def test_generic_treasuries_use_their_own_live_cmt():
    res2 = _run(_fn(_FRED()), instrument=_bond("US2Y"))
    res10 = _run(_fn(_FRED()), instrument=_bond("US10Y"))
    s2, s10 = res2.data["summary"], res10.data["summary"]
    # par bond at the CMT yield: YTM equals the CMT yield
    assert s2["ytm"] == pytest.approx(0.0362, abs=1e-9)
    assert s10["ytm"] == pytest.approx(0.0411, abs=1e-9)
    assert s2["maturity_years"] == 2.0 and s10["maturity_years"] == 10.0
    assert s2["spread_bps"] == pytest.approx((0.0362 - 0.0411) * 10_000)
    assert s10["spread_bps"] == pytest.approx(0.0, abs=1e-6)
    assert s2["as_of"] == "2026-11-06"
    assert res2.sources == ["fred"]
    d2 = {r["metric"]: r["value"] for r in res2.data["rows"]}
    d10 = {r["metric"]: r["value"] for r in res10.data["rows"]}
    assert d2["modified_duration"] < d10["modified_duration"]


def test_manifest_param_names_are_honoured():
    res = _run(_fn(_FRED()), instrument=_bond("XS1234567890"), price=95.0, coupon=5.0,
               years_to_maturity=7, frequency=1, benchmark=4.0)
    s = res.data["summary"]
    assert s["maturity_years"] == 7.0 and s["frequency"] == 1
    assert s["benchmark_rate"] == pytest.approx(0.04)
    assert s["ytm"] > 0.05  # bought below par


def test_non_generic_bond_without_inputs_is_an_input_error():
    res = _run(_fn(_FRED()), instrument=_bond("XS1234567890"))
    assert res.data["status"] == "input_error"
    assert "price" in res.data["reason"] and "coupon" in res.data["reason"]


def test_cmt_outage_is_honest_not_a_static_bond():
    res = _run(_fn(_FRED(fail={"DGS2"})), instrument=_bond("US2Y"))
    assert res.data["status"] == "provider_unavailable"
    assert "DGS2" in res.data["reason"]


def test_no_static_benchmark_fallback():
    res = _run(_fn(_FRED(fail={"DGS10"})), instrument=_bond("XS1"), price=99, coupon=4, years=5)
    assert res.data["summary"]["spread_vs_benchmark"] is None
    assert any("benchmark" in w.lower() for w in res.warnings)


def test_named_benchmark_selects_the_live_10y():
    fred = _FRED()
    res = _run(_fn(fred), instrument=_bond("US2Y"), benchmark="UST10Y")
    assert res.data["summary"]["benchmark_rate"] == pytest.approx(0.0411)
    assert "DGS10" in fred.calls


@pytest.mark.parametrize("sym, rate, years", [("US1M", 4.33, 1 / 12), ("US3M", 4.30, 0.25)])
def test_bills_shorter_than_a_coupon_period_have_bill_durations(sym, rate, years):
    series = {"US1M": "DGS1MO", "US3M": "DGS3MO"}[sym]
    res = _run(_fn(_FRED({series: rate, "DGS10": 4.11})), instrument=_bond(sym))
    rows = {r["metric"]: r["value"] for r in res.data["rows"]}
    y = rate / 100
    assert res.data["summary"]["ytm"] == pytest.approx(y, abs=1e-12)
    assert rows["macaulay_duration"] == pytest.approx(years)
    assert rows["modified_duration"] == pytest.approx(years / (1 + y * years))
    assert rows["convexity"] == pytest.approx(2 * years**2 / (1 + y * years) ** 2)


def test_six_month_bill_keeps_the_coupon_period_model():
    res = _run(_fn(_FRED({"DGS6MO": 4.2, "DGS10": 4.11})), instrument=_bond("US6M"))
    rows = {r["metric"]: r["value"] for r in res.data["rows"]}
    assert rows["macaulay_duration"] == pytest.approx(0.5)


def test_price_only_override_keeps_live_coupon_and_maturity():
    res = _run(_fn(_FRED()), instrument=_bond("US10Y"), price=98.0)
    s = res.data["summary"]
    assert s["coupon_rate"] == pytest.approx(0.0411)
    assert s["maturity_years"] == 10.0
    assert s["ytm"] > 0.0411  # bought below par
