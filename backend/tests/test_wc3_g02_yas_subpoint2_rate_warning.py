"""XCON-2 (YAS, sub-0.2 part): a coupon or benchmark read as a decimal is not silent.

A coupon of 0.1 with no unit stated is read as the decimal 0.1 (10%) because the
decimal form is the documented convention (0.04, 0.0425 in the existing tests).
That reading stays, but it must carry a warning naming the percent that was
priced, the same way GREEKS does for plain decimal rates. A stated unit
(assume_decimal=true) or a percent above 1 is read without that warning.
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


def _decimal_warnings(res):
    return [w for w in res.warnings if "decimal" in w.lower()]


def test_plain_decimal_coupon_below_point_two_is_priced_and_warned() -> None:
    res = _run(coupon=0.1)
    assert res.data.get("status") is None
    assert res.data["summary"]["coupon_rate"] == 0.1
    warnings = _decimal_warnings(res)
    assert warnings, "a coupon read as a decimal must carry a warning"
    text = " ".join(warnings)
    assert "coupon 0.1" in text
    assert "10%" in text
    assert "assume_decimal" in text or "0.1%" in text


def test_plain_decimal_benchmark_below_point_two_is_warned() -> None:
    res = _run(coupon=4.25, benchmark=0.1)
    assert res.data.get("status") is None
    text = " ".join(_decimal_warnings(res))
    assert "benchmark 0.1" in text
    assert "10%" in text


def test_stated_decimal_unit_has_no_decimal_ambiguity_warning() -> None:
    res = _run(coupon=0.1, assume_decimal=True)
    assert res.data["summary"]["coupon_rate"] == 0.1
    assert not _decimal_warnings(res)


def test_percent_coupon_has_no_decimal_ambiguity_warning() -> None:
    res = _run(coupon=4.25)
    assert res.data["summary"]["coupon_rate"] == 0.0425
    assert not _decimal_warnings(res)


def test_zero_coupon_has_no_decimal_ambiguity_warning() -> None:
    res = _run(coupon=0.0)
    assert not _decimal_warnings(res)
