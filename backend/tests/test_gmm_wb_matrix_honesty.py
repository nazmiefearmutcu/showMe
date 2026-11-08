"""GMM (Global Macro Matrix) honesty tests: country mapping, completeness, staleness.

Network is patched: ``showme.providers._http.get_client`` is replaced with an
in-memory fake that answers World Bank indicator requests from a table.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.macro import gmm as gmm_mod
from showme.engine.functions.macro.gmm import GMMFunction

INDICATORS = ("NY.GDP.MKTP.KD.ZG", "FP.CPI.TOTL.ZG", "SL.UEM.TOTL.ZS", "GC.DOD.TOTL.GD.ZS")


def _run(coro):
    return asyncio.run(coro)


class _Resp:
    def __init__(self, payload: Any) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> Any:
        return self._payload


class _FakeWorldBank:
    """Answers /country/<list>/indicator/<code> from ``table``.

    ``table[(wb_request_code, indicator)]`` is an observation dict; a missing
    entry means World Bank returned no observation for that cell.
    """

    def __init__(self, table: dict[tuple[str, str], dict[str, Any]]) -> None:
        self.table = table
        self.urls: list[str] = []

    async def get(self, url: str, params: Any = None) -> _Resp:
        self.urls.append(url)
        head, ind = url.rsplit("/indicator/", 1)
        param = head.split("/country/", 1)[1]
        obs = [self.table[(c, ind)] for c in param.split(";") if (c, ind) in self.table]
        return _Resp([{"page": 1, "pages": 1, "total": len(obs)}, obs])


def _obs(country_id: str, iso3: str, indicator: str, value: float, year: int) -> dict[str, Any]:
    return {
        "indicator": {"id": indicator},
        "country": {"id": country_id, "value": ""},
        "countryiso3code": iso3,
        "date": str(year),
        "value": value,
    }


@pytest.fixture
def fake_wb(monkeypatch) -> _FakeWorldBank:
    table: dict[tuple[str, str], dict[str, Any]] = {}
    # The euro-area aggregate is requested as EMU; World Bank answers with id XC.
    for ind in INDICATORS:
        table[("EMU", ind)] = _obs("XC", "EMU", ind, 1.5, 2025)
        table[("CH", ind)] = _obs("CH", "CHE", ind, 2.0, 2025)
        table[("DE", ind)] = _obs("DE", "DEU", ind, 3.0, 2025)
    fake = _FakeWorldBank(table)

    async def _get_client() -> _FakeWorldBank:
        return fake

    import showme.providers._http as http_mod

    monkeypatch.setattr(http_mod, "get_client", _get_client)
    return fake


def _requested_codes(fake: _FakeWorldBank) -> set[str]:
    codes: set[str] = set()
    for url in fake.urls:
        param = url.split("/country/", 1)[1].split("/indicator/", 1)[0]
        codes.update(param.split(";"))
    return codes


# ── GMM#2: EZ is the euro area, CH has a name, unknown codes are flagged ──


def test_ez_is_euro_area_aggregate_not_germany(fake_wb: _FakeWorldBank) -> None:
    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["EZ", "CH"]))
    rows = {r["country_code"]: r for r in result.data["rows"]}

    assert set(rows) == {"EZ", "CH"}
    assert rows["EZ"]["country"] == "Euro area"
    assert rows["CH"]["country"] == "Switzerland"
    # EZ values come from the EMU aggregate, never from the German series.
    assert rows["EZ"]["gdp_growth"] == 1.5
    assert "DE" not in _requested_codes(fake_wb)
    assert "EMU" in _requested_codes(fake_wb)
    assert not any(r["country"] == "Germany" for r in result.data["rows"])


def test_unknown_country_code_is_flagged_not_silent(fake_wb: _FakeWorldBank) -> None:
    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["US", "ZZ"]))
    assert any("ZZ" in w for w in result.warnings), result.warnings
    # Known codes do not produce a warning.
    result_ok = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["US", "CH"]))
    assert not any("CH" in w or "US" in w for w in result_ok.warnings)


def test_eu_resolves_to_european_union_aggregate() -> None:
    resolved = gmm_mod._resolve_countries(["EU"])
    assert resolved == {"EU": "European Union"}
    assert gmm_mod._WB_REQUEST_CODE["EU"] == "EUU"


# ── GMM#3: a row missing any component gets no score, not a partial one ──


def _patch_table(monkeypatch, table: dict[tuple[str, str], dict[str, Any]]) -> _FakeWorldBank:
    fake = _FakeWorldBank(table)

    async def _get_client() -> _FakeWorldBank:
        return fake

    import showme.providers._http as http_mod

    monkeypatch.setattr(http_mod, "get_client", _get_client)
    return fake


def test_row_missing_debt_gets_null_score_and_sorts_last(monkeypatch) -> None:
    table: dict[tuple[str, str], dict[str, Any]] = {}
    # US has all four indicators; JP has no debt/GDP observation at all.
    values = {
        "NY.GDP.MKTP.KD.ZG": 2.0,
        "FP.CPI.TOTL.ZG": 5.0,
        "SL.UEM.TOTL.ZS": 4.0,
        "GC.DOD.TOTL.GD.ZS": 100.0,
    }
    for ind, val in values.items():
        table[("US", ind)] = _obs("US", "USA", ind, val, 2025)
    for ind in ("NY.GDP.MKTP.KD.ZG", "FP.CPI.TOTL.ZG", "SL.UEM.TOTL.ZS"):
        table[("JP", ind)] = _obs("JP", "JPN", ind, 1.0, 2025)
    _patch_table(monkeypatch, table)

    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["JP", "US"]))
    rows = {r["country_code"]: r for r in result.data["rows"]}

    # 5 + 4 + 0.05*100 - 2 = 12.0 ; the JP row must not be scored as if debt were 0.
    assert rows["US"]["score"] == pytest.approx(12.0)
    assert rows["JP"]["score"] is None
    assert rows["JP"]["score_missing"] == ["debt_gdp"]
    assert rows["US"]["score_missing"] == []
    assert result.data["rows"][0]["country_code"] == "US"
    assert result.data["rows"][-1]["country_code"] == "JP"


def test_composite_score_requires_all_four_components() -> None:
    partial = {"inflation": 3.0, "unemployment": 4.0, "debt_gdp": None, "gdp_growth": 1.0}
    assert gmm_mod._composite_score(partial) is None
    full = {"inflation": 3.0, "unemployment": 4.0, "debt_gdp": 60.0, "gdp_growth": 1.0}
    assert gmm_mod._composite_score(full) == pytest.approx(3.0 + 4.0 + 3.0 - 1.0)
