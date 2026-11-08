"""SRSK review regressions: honest states for unscored and FRED-only rows.

No network: the World Bank adapter seam and the FRED client are faked.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.bond.srsk import SRSKFunction


class _Col:
    def __init__(self, value: float) -> None:
        self.iloc = [value]


class _FakeFred:
    _SERIES: dict[str, float] = {
        "DGS10": 2.0,
        "IRLTLT01DEM156N": 3.5,
        "IRLTLT01TRM156N": 9.0,
    }

    async def series(self, series_id: str) -> dict[str, _Col]:
        return {"value": _Col(self._SERIES[series_id])}


class _NoWorldBank:
    async def indicator(self, iso3: str, indicator: str) -> Any:
        return [{"page": 1, "total": 0}, None]


class _PartialWorldBank:
    _BY_ISO3: dict[str, dict[str, float]] = {
        "TUR": {
            "GC.DOD.TOTL.GD.ZS": 34.0,
            "FI.RES.TOTL.MO": 3.5,
            "BN.CAB.XOKA.GD.ZS": -4.5,
            "FP.CPI.TOTL.ZG": 53.0,
        },
        "USA": {
            "GC.DOD.TOTL.GD.ZS": 121.0,
            "FI.RES.TOTL.MO": 0.6,
            "BN.CAB.XOKA.GD.ZS": -3.0,
            "FP.CPI.TOTL.ZG": 3.4,
        },
    }

    async def indicator(self, iso3: str, indicator: str) -> Any:
        value = self._BY_ISO3.get(iso3, {}).get(indicator)
        return [{"page": 1, "total": 1}, [{"value": value, "date": "2024"}]]


@pytest.fixture
def no_network(monkeypatch: pytest.MonkeyPatch) -> None:
    import showme.providers._http as http_mod

    class _Dead:
        def get(self, *a: Any, **k: Any) -> Any:
            raise OSError("network disabled in tests")

    monkeypatch.setattr(http_mod, "get_client", lambda: _Dead(), raising=False)


# SRSK#4-RQ: a FRED-configured US row with no World Bank macro must not be
# pinned to a constant 0.0 spread and a 0.0 PD labelled as a live FRED reading.
def test_fred_configured_us_without_macro_has_null_spread_and_pd(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_NoWorldBank(), fred=_FakeFred()))
    out = asyncio.run(fn.execute(countries="US,XX,DE"))
    by_country = {row["country"]: row for row in out.data["rows"]}
    us = by_country["US"]
    assert us["risk_score"] is None
    assert us["proxy_spread_pct"] is None, us
    assert us["pd_1y_pct"] is None, us
    assert us["pd_1y_proxy"] is None, us
    assert us["source_mode"] == "unavailable", us
    assert out.data["cards"]["highest_pd_country"] is None
    assert "fred" in out.sources  # DE is still a real FRED differential


def test_fred_configured_us_with_macro_keeps_macro_spread_not_zero(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_PartialWorldBank(), fred=_FakeFred()))
    out = asyncio.run(fn.execute(countries="US,TR"))
    us = {row["country"]: row for row in out.data["rows"]}["US"]
    assert us["risk_score"] is not None
    assert us["proxy_spread_pct"] is not None and us["proxy_spread_pct"] > 0.0, us
    assert us["source_mode"] == "worldbank", us
    assert "self-spread is zero" not in (us["note"] or "")


def test_fred_only_xx_and_us_is_not_status_ok(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_NoWorldBank(), fred=_FakeFred()))
    out = asyncio.run(fn.execute(countries="US,XX"))
    assert out.data["status"] in {"empty", "provider_unavailable"}, out.data
    assert out.data["rows"] == []


# SRSK#1: recovery is a probability bounded by the seed's max 0.95. Out-of-range
# input must be an explicit input_error, never a PD above 100% (R=1.0 gave 668%).
@pytest.mark.parametrize("bad", [1.0, 0.99, 1.5, -0.1, "abc", float("nan")])
def test_out_of_range_recovery_is_input_error(no_network: None, bad: Any) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_PartialWorldBank()))
    out = asyncio.run(fn.execute(countries="TR,US", recovery=bad))
    assert out.data["status"] == "input_error", out.data
    assert out.data["rows"] == []
    assert out.data.get("reason")
    assert out.data.get("next_actions")


def test_boundary_recovery_is_accepted_and_uses_the_hull_identity(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_PartialWorldBank()))
    out = asyncio.run(fn.execute(countries="TR,US", recovery=0.95))
    assert out.data["status"] == "ok"
    for row in out.data["rows"]:
        assert row["pd_1y_pct"] == pytest.approx(row["proxy_spread_pct"] / (1 - 0.95), rel=1e-6), row


def test_default_recovery_still_works(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_PartialWorldBank()))
    out = asyncio.run(fn.execute(countries="TR"))
    assert out.data["status"] == "ok"
    assert out.data["rows"][0]["recovery"] == 0.4


# SRSK#7: a row's as_of must not be the year of whichever leg happened to come
# first. India had a 2018 debt leg and 2025 reserves/CAB/CPI; the row claimed 2018
# as its single date with no per-leg detail.
class _DatedWorldBank:
    _DATA = {
        "debt_to_gdp": ("GC.DOD.TOTL.GD.ZS", 70.0, "2018"),
        "reserves_months": ("FI.RES.TOTL.MO", 9.0, "2025"),
        "current_account_gdp": ("BN.CAB.XOKA.GD.ZS", -1.0, "2025"),
        "inflation_pct": ("FP.CPI.TOTL.ZG", 4.0, "2025"),
    }

    async def indicator(self, iso3: str, indicator: str) -> Any:
        for _key, (code, value, year) in self._DATA.items():
            if code == indicator:
                return [{"page": 1, "total": 1}, [{"value": value, "date": year}]]
        return [{"page": 1, "total": 0}, None]


def test_row_as_of_is_the_oldest_leg_with_per_leg_dates(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_DatedWorldBank()))
    out = asyncio.run(fn.execute(countries="IN"))
    row = out.data["rows"][0]
    assert row["as_of"] == "2018", row
    assert row["as_of_by_leg"] == {
        "debt_to_gdp": "2018",
        "reserves_months": "2025",
        "current_account_gdp": "2025",
        "inflation_pct": "2025",
    }, row
    assert out.data["cards"]["as_of"] == "2018"


# SRSK#8: the card is labelled "Highest PD", so it must pick the highest PD, not
# the highest composite score. With FRED refining the spread, the two can diverge.
class _ScoreWorldBank:
    """TR gets a high composite score; DE a moderate one (both with real macro)."""

    _BY_ISO3 = {
        "TUR": {"GC.DOD.TOTL.GD.ZS": 34.0, "FI.RES.TOTL.MO": 3.5, "BN.CAB.XOKA.GD.ZS": -4.5, "FP.CPI.TOTL.ZG": 53.0},
        "DEU": {"GC.DOD.TOTL.GD.ZS": 64.0, "FI.RES.TOTL.MO": 4.0, "BN.CAB.XOKA.GD.ZS": 2.0, "FP.CPI.TOTL.ZG": 2.3},
    }

    async def indicator(self, iso3: str, indicator: str) -> Any:
        value = self._BY_ISO3.get(iso3, {}).get(indicator)
        return [{"page": 1, "total": 1}, [{"value": value, "date": "2024"}]]


class _SpreadFred:
    """UST 2%; DE 12% (spread 10, large PD) and TR 3% (spread 1, small PD)."""

    _SERIES = {"DGS10": 2.0, "IRLTLT01DEM156N": 12.0, "IRLTLT01TRM156N": 3.0}

    async def series(self, series_id: str) -> dict[str, _Col]:
        return {"value": _Col(self._SERIES[series_id])}


def test_highest_pd_card_picks_highest_pd_not_highest_score(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_ScoreWorldBank(), fred=_SpreadFred()))
    out = asyncio.run(fn.execute(countries="TR,DE"))
    rows = {r["country"]: r for r in out.data["rows"]}
    assert rows["TR"]["risk_score"] > rows["DE"]["risk_score"]  # precondition: score says TR
    assert rows["DE"]["pd_1y_pct"] > rows["TR"]["pd_1y_pct"]  # PD says DE
    assert out.data["cards"]["highest_pd_country"] == "DE", out.data["cards"]
    assert out.data["cards"]["highest_pd"] == pytest.approx(rows["DE"]["pd_1y_pct"], abs=1e-4)
    assert out.data["summary"]["highest_risk_country"] == "DE"


# SRSK#6: a composite built from 3 of 4 legs is not comparable with a full
# 4-leg score. The row must say how many legs it used, and a partial score must
# not lead the highest-PD card over a full-coverage country.
class _NoDebtWorldBank:
    """DE has no debt/GDP observation (as in the live pull); TR is complete."""

    _BY_ISO3 = {
        "TUR": {"GC.DOD.TOTL.GD.ZS": 34.0, "FI.RES.TOTL.MO": 3.5, "BN.CAB.XOKA.GD.ZS": -4.5, "FP.CPI.TOTL.ZG": 53.0},
        "DEU": {"FI.RES.TOTL.MO": 4.0, "BN.CAB.XOKA.GD.ZS": 2.0, "FP.CPI.TOTL.ZG": 2.3},
    }

    async def indicator(self, iso3: str, indicator: str) -> Any:
        value = self._BY_ISO3.get(iso3, {}).get(indicator)
        return [{"page": 1, "total": 1}, [{"value": value, "date": "2024"}]]


def test_partial_leg_row_reports_its_coverage(no_network: None) -> None:
    fn = SRSKFunction(FunctionDeps(worldbank=_NoDebtWorldBank()))
    out = asyncio.run(fn.execute(countries="TR,DE"))
    rows = {r["country"]: r for r in out.data["rows"]}
    assert rows["TR"]["legs_present"] == 4 and rows["TR"]["legs_total"] == 4
    assert rows["DE"]["legs_present"] == 3 and rows["DE"]["legs_total"] == 4, rows["DE"]
    assert out.data["summary"]["partial_coverage_countries"] == 1


def test_partial_leg_row_never_leads_the_highest_pd_card(no_network: None) -> None:
    # DE has the larger PD proxy from fewer legs; the card must use the full-coverage TR.
    fn = SRSKFunction(FunctionDeps(worldbank=_NoDebtWorldBank(), fred=_SpreadFred()))
    out = asyncio.run(fn.execute(countries="TR,DE"))
    rows = {r["country"]: r for r in out.data["rows"]}
    assert rows["DE"]["pd_1y_pct"] > rows["TR"]["pd_1y_pct"]  # precondition
    assert out.data["cards"]["highest_pd_country"] == "TR", out.data["cards"]


# SRSK#3: one hung World Bank country must not take the whole Wide-12 call past
# the function timeout. Countries that finish keep their real rows; the hung one
# is an explicit unavailable row, never a fabricated value.
class _HangingWorldBank:
    _BY_ISO3 = _PartialWorldBank._BY_ISO3

    async def indicator(self, iso3: str, indicator: str) -> Any:
        if iso3 == "USA":
            await asyncio.sleep(3600)
        value = self._BY_ISO3.get(iso3, {}).get(indicator)
        return [{"page": 1, "total": 1}, [{"value": value, "date": "2024"}]]


def test_hung_country_is_bounded_and_others_keep_real_rows(no_network: None, monkeypatch: pytest.MonkeyPatch) -> None:
    from showme.engine.functions.bond import srsk as srsk_mod

    monkeypatch.setattr(srsk_mod, "_CALL_BUDGET_S", 0.3, raising=False)
    fn = SRSKFunction(FunctionDeps(worldbank=_HangingWorldBank()))
    # Guard: without a call budget the hung fetch would run forever; cap the test itself.
    out = asyncio.run(asyncio.wait_for(fn.execute(countries="TR,US"), timeout=5.0))
    assert out.data["status"] == "ok", out.data
    rows = {r["country"]: r for r in out.data["rows"]}
    assert rows["TR"]["risk_score"] is not None
    assert rows["US"]["risk_score"] is None and rows["US"]["pd_1y_pct"] is None
    assert any("US" in w and "timed out" in w for w in out.warnings), out.warnings


# SRSK#2: the PD is a linear transform of an uncalibrated equal-weight macro
# score. The output must say so, per row and on the card, so it is not read as a
# market-implied default probability.
def test_pd_basis_labels_macro_proxy_rows_and_card(no_network: None) -> None:
    out = asyncio.run(SRSKFunction(FunctionDeps(worldbank=_PartialWorldBank())).execute(countries="TR,US"))
    for row in out.data["rows"]:
        assert row["pd_basis"] == "macro_composite_proxy", row
    assert out.data["cards"]["pd_basis"] == "macro_composite_proxy"
    assert out.data["summary"]["pd_calibration"] == "uncalibrated"
    assert "not" in out.data["methodology"].lower() and "uncalibrated" in out.data["methodology"].lower()


def test_pd_basis_labels_fred_refined_rows(no_network: None) -> None:
    out = asyncio.run(
        SRSKFunction(FunctionDeps(worldbank=_ScoreWorldBank(), fred=_SpreadFred())).execute(countries="TR,DE")
    )
    basis = {r["country"]: r["pd_basis"] for r in out.data["rows"]}
    assert basis == {"TR": "fred_yield_differential", "DE": "fred_yield_differential"}, basis
