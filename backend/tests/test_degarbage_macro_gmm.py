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

OK_STATUSES = {"ok", "empty"}


def _run(coro):
    return asyncio.run(coro)


def test_resolve_countries_defaults_to_majors():
    majors = _resolve_countries(None)
    assert "US" in majors and "CN" in majors and "DE" in majors
    assert majors["US"] == "United States"
    # euro-area proxy collapses to Germany series
    assert "DE" in _resolve_countries(["EZ"])


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


def test_gmm_live_returns_real_worldbank_data():
    """Live happy path against the keyless World Bank API.

    Guarded: on any network error we assert the graceful provider_unavailable
    shape instead, so the suite stays green offline.
    """
    fn = GMMFunction(deps=FunctionDeps())
    result = _run(fn.execute(countries=["US", "DE", "JP"], top_n=10))
    data = result.data

    # Old hardcoded reference table must never be the happy path.
    serialized = repr(data["rows"])
    assert "PMI" not in serialized
    assert "Retail sales" not in serialized

    if data["status"] == "provider_unavailable":
        # Offline / rate-limited: graceful shape, no fabricated rows.
        assert data["rows"] == []
        assert result.warnings
        pytest.skip("World Bank API unreachable; verified graceful outage shape.")

    assert data["status"] in OK_STATUSES
    assert result.sources == ["worldbank"]
    assert data["methodology"]
    assert isinstance(data["field_dictionary"], dict) and data["field_dictionary"]

    rows = data["rows"]
    assert rows, "live fetch should return at least one country row"
    # At least one row must carry a real numeric macro value (not all null).
    has_real_value = any(
        any(
            isinstance(r.get(k), (int, float))
            for k in ("gdp_growth", "inflation", "unemployment", "debt_gdp")
        )
        for r in rows
    )
    assert has_real_value, "live World Bank rows must contain real numbers"
    # Every row carries the ISO code and a country label.
    for r in rows:
        assert r.get("country_code")
        assert r.get("country")
