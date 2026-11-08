"""YAS honesty regressions (wc1-g34): YAS#4 convexity unit and value, YAS#5
data_mode, methodology text and the never-read provider_mode input.
"""

from __future__ import annotations

import asyncio

import pandas as pd
import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.core.instrument import AssetClass, Instrument
from showme.engine.functions.bond.yas import YASFunction, _bond_pv
from showme.manifest import REGISTRY, load_seeds

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


def _run(symbol="XS1234567890", **params):
    deps = FunctionDeps()
    deps.fred = _FRED()
    return asyncio.run(YASFunction(deps).execute(
        instrument=Instrument(symbol=symbol, asset_class=AssetClass.BOND), **params))


def _rows(res) -> dict[str, dict]:
    return {r["metric"]: r for r in res.data["rows"]}


# ---- YAS#4: convexity is years^2 and matches the finite difference ----------


def test_yas4_convexity_matches_finite_difference_in_years_squared() -> None:
    res = _run(price=100.0, coupon=0.04, frequency=4, years_to_maturity=30)
    conv = _rows(res)["convexity"]["value"]
    coupon, freq, n = 0.04, 4, 120
    c = coupon / freq  # _bond_pv takes the per-period coupon as a fraction of face
    def p(y):
        return _bond_pv(100.0, c, y / freq, n)
    h = 1e-4
    p0 = p(0.04)
    fd = (p(0.04 + h) - 2 * p0 + p(0.04 - h)) / (h * h) / p0
    assert conv == pytest.approx(fd, rel=1e-4)


def test_yas4_convexity_value_is_about_421_for_30y_quarterly_par() -> None:
    res = _run(price=100.0, coupon=0.04, frequency=4, years_to_maturity=30)
    conv = _rows(res)["convexity"]["value"]
    assert 400.0 < conv < 440.0


def test_yas4_convexity_row_is_labelled_years_squared() -> None:
    res = _run(price=100.0, coupon=0.04, frequency=4, years_to_maturity=30)
    assert _rows(res)["convexity"]["unit"] == "years^2"
    assert "years" in res.data["field_dictionary"]["convexity"]


# ---- YAS#5: data_mode is emitted and honest --------------------------------


def test_yas5_user_terms_report_user_input_data_mode() -> None:
    res = _run(price=99.5, coupon=0.0425, years_to_maturity=10, frequency=2)
    assert res.data["data_mode"] == "user_input"
    assert res.metadata["data_mode"] == "user_input"


def test_yas5_cmt_derived_bond_reports_modeled_data_mode() -> None:
    deps = FunctionDeps()
    deps.fred = _FRED()
    res = asyncio.run(YASFunction(deps).execute(
        instrument=Instrument(symbol="US10Y", asset_class=AssetClass.BOND)))
    assert res.data["data_mode"] == "modeled"
    assert res.metadata["data_mode"] == "modeled"


def test_yas5_provider_mode_is_not_a_declared_input() -> None:
    """provider_mode was declared but never read; the mode is now derived from the data path."""
    load_seeds()
    yas = REGISTRY.get("YAS")
    assert "provider_mode" not in [i.name for i in yas.inputs]
    assert "provider_mode" not in (yas.defaults or {})


def test_yas5_methodology_states_the_real_bracket_and_no_snapshot() -> None:
    load_seeds()
    text = REGISTRY.get("YAS").methodology
    assert "cached_snapshot" not in text
    assert "[-0.99, 5.0]" not in text
    assert "-1%" in text and "500%" in text


def test_yas5_spread_unit_text_is_basis_points_not_times_100() -> None:
    load_seeds()
    yas = REGISTRY.get("YAS")
    assert "× 100 bp" not in yas.methodology
    assert "10,000" in yas.methodology or "10000" in yas.methodology
