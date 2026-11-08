"""P2A G14 — OVME states the rate it used and the Heston parameters it priced with.

OVME#2: live_rate always read DGS1 (the 1-year yield) whatever the maturity,
the Heston parameters were fixed inside the handler and not echoed, and the
FRED source was computed but dropped from the response sources.
"""
from __future__ import annotations

import asyncio

import pandas as pd

from showme.engine.functions.derivative import ovme as ovme_mod
from showme.engine.functions.derivative.ovme import OVMEFunction


class _FakeFred:
    def __init__(self, value_pct: float) -> None:
        self.value_pct = value_pct
        self.requested: list[str] = []

    async def series(self, series_id: str, frequency: str = "d", **_: object) -> pd.DataFrame:
        self.requested.append(series_id)
        return pd.DataFrame({"value": [self.value_pct]})


class _Deps:
    def __init__(self, fred: object | None) -> None:
        self.fred = fred


def _run(fred: _FakeFred | None, **params):
    fn = OVMEFunction()
    fn.deps = _Deps(fred)
    return asyncio.run(fn.execute(**params))


def test_live_rate_uses_series_matching_the_maturity() -> None:
    fred = _FakeFred(4.2)
    _run(fred, spot=100, strike=100, years_to_expiry=0.5, vol=0.25, live_rate=True)
    assert fred.requested == ["DGS6MO"]


def test_live_rate_three_month_option_uses_three_month_bill() -> None:
    fred = _FakeFred(5.1)
    _run(fred, spot=100, strike=100, years_to_expiry=0.25, vol=0.25, live_rate=True)
    assert fred.requested == ["DGS3MO"]


def test_live_rate_ten_year_option_uses_ten_year_yield() -> None:
    fred = _FakeFred(4.4)
    _run(fred, spot=100, strike=100, years_to_expiry=10, vol=0.25, live_rate=True)
    assert fred.requested == ["DGS10"]


def test_live_rate_is_reported_with_its_series_and_source() -> None:
    fred = _FakeFred(4.2)
    res = _run(fred, spot=100, strike=100, years_to_expiry=0.5, vol=0.25, live_rate=True)
    assert abs(res.data["rate"] - 0.042) < 1e-12
    assert res.data["rate_source"] == "fred_DGS6MO"
    assert "fred" in res.sources


def test_default_rate_is_labelled_as_a_default() -> None:
    res = _run(None, spot=100, strike=100, years_to_expiry=0.5, vol=0.25)
    assert res.data["rate_source"] == "default_0.045"
    assert "fred" not in res.sources


def test_heston_parameters_are_echoed_and_labelled_uncalibrated() -> None:
    res = _run(None, spot=100, strike=100, years_to_expiry=0.5, vol=0.25,
               model="heston", paths=2000, steps=20)
    hp = res.data["heston_params"]
    assert hp["kappa"] == 2.0
    assert hp["sigma"] == 0.4
    assert hp["rho"] == -0.6
    assert abs(hp["theta"] - 0.25 ** 2) < 1e-12
    assert abs(hp["v0"] - 0.25 ** 2) < 1e-12
    assert hp["calibrated"] is False


def test_cmt_series_table_covers_standard_tenors() -> None:
    assert ovme_mod._cmt_series_for(0.25)[0] == "DGS3MO"
    assert ovme_mod._cmt_series_for(1.0)[0] == "DGS1"
    assert ovme_mod._cmt_series_for(30.0)[0] == "DGS30"
