"""De-garbage regression tests for GMM (Global Macro Movers).

GMM used to depend on the key-gated ``tradingeconomics`` adapter and silently
fall back to a hardcoded 3-row reference table (US CPI 3.1, EU PMI 51.2,
GB retail -0.2). It now fetches real, keyless cross-country macro indicators
from the World Bank open-data API.

These tests:
  * assert the old hardcoded constants are gone from the happy path,
  * assert a successful live fetch returns status="ok" with real rows,
  * SKIP cleanly offline by asserting the graceful provider_unavailable shape.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro.gmm import (
    GMMFunction,
    _composite_score,
    _parse_wb_series,
    _resolve_countries,
)



def _run(coro):
    return asyncio.run(coro)


def test_resolve_countries_defaults_to_majors():
    majors = _resolve_countries(None)
    assert "US" in majors and "CN" in majors and "DE" in majors
    assert majors["US"] == "United States"
    # euro-area proxy collapses to Germany series
    assert "EZ" in _resolve_countries(["EZ"])  # euro area aggregate, not DE


def test_parse_wb_series_extracts_latest_non_null():
    payload = [
        {"page": 1, "pages": 1, "per_page": 50, "total": 2},
        [
            {
                "indicator": {"id": "FP.CPI.TOTL.ZG"},
                "country": {"id": "US", "value": "United States"},
                "countryiso3code": "USA",
                "date": "2023",
                "value": 4.116,
            },
            {
                "indicator": {"id": "FP.CPI.TOTL.ZG"},
                "country": {"id": "US", "value": "United States"},
                "countryiso3code": "USA",
                "date": "2022",
                "value": 8.0,
            },
            {
                "indicator": {"id": "FP.CPI.TOTL.ZG"},
                "country": {"id": "TR", "value": "Turkiye"},
                "countryiso3code": "TUR",
                "date": "2021",
                "value": None,  # null is skipped
            },
        ],
    ]
    parsed = _parse_wb_series(payload)
    assert parsed["US"][0] == 4.116  # latest year wins
    assert parsed["US"][1] == 2023
    assert "TR" not in parsed  # null observation dropped


def test_parse_wb_series_handles_garbage():
    assert _parse_wb_series(None) == {}
    assert _parse_wb_series([{"message": "err"}]) == {}
    assert _parse_wb_series(["meta", "not-a-list"]) == {}


def test_composite_score_partial_and_empty():
    assert _composite_score({"inflation": None, "unemployment": None,
                             "debt_gdp": None, "gdp_growth": None}) is None
    # inflation 5 + unemployment 4 + 0.05*100 debt - growth 2 = 12
    score = _composite_score(
        {"inflation": 5.0, "unemployment": 4.0, "debt_gdp": 100.0, "gdp_growth": 2.0}
    )
    assert score == pytest.approx(12.0)


def test_provider_unavailable_shape_is_honest():
    """When the network fails the handler must NOT fabricate numbers."""
    import showme.engine.functions.macro.gmm as gmm_mod

    async def _boom(*_a, **_k):
        raise RuntimeError("network down")

    orig = gmm_mod._fetch_worldbank_matrix
    gmm_mod._fetch_worldbank_matrix = _boom
    try:
        fn = GMMFunction(deps=FunctionDeps())
        result = _run(fn.execute())
    finally:
        gmm_mod._fetch_worldbank_matrix = orig

    assert result.data["status"] == "provider_unavailable"
    assert result.data["rows"] == []
    assert result.sources == ["worldbank"]
    assert result.warnings, "outage must carry an honest warning"
    assert "next_actions" in result.data
    assert "methodology" in result.data and result.data["methodology"]


class _FakeWorldBank:
    """Serves World Bank v2 indicator payloads from a fixed table; no network."""

    def __init__(self, table):
        self.table = table

    async def get(self, url, params=None):
        head, ind = url.rsplit("/indicator/", 1)
        codes = head.split("/country/", 1)[1].split(";")
        obs = [self.table[(c, ind)] for c in codes if (c, ind) in self.table]
        return _FakeResp([{"page": 1, "pages": 1, "total": len(obs)}, obs])


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _wb_obs(code, iso3, ind, value, year):
    return {
        "indicator": {"id": ind},
        "country": {"id": code, "value": ""},
        "countryiso3code": iso3,
        "date": str(year),
        "value": value,
    }


def test_gmm_matrix_rows_from_worldbank_payload(monkeypatch):
    """Happy path: rows built from World Bank-shaped payloads, with no network.

    The fake answers the four indicators for US, DE and JP. Previously this
    test called the live API and only passed or skipped depending on whether
    the network was reachable.
    """
    indicators = [
        "NY.GDP.MKTP.KD.ZG",
        "FP.CPI.TOTL.ZG",
        "SL.UEM.TOTL.ZS",
        "GC.DOD.TOTL.GD.ZS",
    ]
    table = {}
    for code, iso3 in (("US", "USA"), ("DE", "DEU"), ("JP", "JPN")):
        for ind in indicators:
            table[(code, ind)] = _wb_obs(code, iso3, ind, 2.5, 2025)
    fake = _FakeWorldBank(table)

    async def _get_client():
        return fake

    import showme.providers._http as http_mod

    monkeypatch.setattr(http_mod, "get_client", _get_client)

    fn = GMMFunction(deps=FunctionDeps())
    result = _run(fn.execute(countries=["US", "DE", "JP"], top_n=10))
    data = result.data

    # Old hardcoded reference table must never be the happy path.
    serialized = repr(data["rows"])
    assert "PMI" not in serialized
    assert "Retail sales" not in serialized

    assert data["status"] == "ok"
    assert result.sources == ["worldbank"]
    assert data["methodology"]
    assert isinstance(data["field_dictionary"], dict) and data["field_dictionary"]

    rows = data["rows"]
    assert {r["country_code"] for r in rows} == {"US", "DE", "JP"}
    # Every row carries a real numeric value for each indicator.
    for r in rows:
        assert r["country"]
        for k in ("gdp_growth", "inflation", "unemployment", "debt_gdp"):
            assert isinstance(r.get(k), (int, float)), (r["country_code"], k)
