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
