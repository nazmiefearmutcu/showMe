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


# ── GMM#4: observations older than the age limit do not feed the score ──


def test_stale_debt_observation_is_shown_but_not_scored(monkeypatch) -> None:
    monkeypatch.setattr(gmm_mod, "_as_of_year", lambda: 2026)
    table: dict[tuple[str, str], dict[str, Any]] = {}
    # US: every indicator is recent. DE: debt/GDP is a 1990 observation.
    for ind in ("NY.GDP.MKTP.KD.ZG", "FP.CPI.TOTL.ZG", "SL.UEM.TOTL.ZS", "GC.DOD.TOTL.GD.ZS"):
        table[("US", ind)] = _obs("US", "USA", ind, 2.0, 2025)
    table[("DE", "NY.GDP.MKTP.KD.ZG")] = _obs("DE", "DEU", "NY.GDP.MKTP.KD.ZG", 0.5, 2025)
    table[("DE", "FP.CPI.TOTL.ZG")] = _obs("DE", "DEU", "FP.CPI.TOTL.ZG", 2.5, 2025)
    table[("DE", "SL.UEM.TOTL.ZS")] = _obs("DE", "DEU", "SL.UEM.TOTL.ZS", 3.5, 2025)
    table[("DE", "GC.DOD.TOTL.GD.ZS")] = _obs("DE", "DEU", "GC.DOD.TOTL.GD.ZS", 20.85, 1990)
    _patch_table(monkeypatch, table)

    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["US", "DE"]))
    rows = {r["country_code"]: r for r in result.data["rows"]}

    de = rows["DE"]
    # The value and its year stay visible so the staleness is auditable...
    assert de["debt_gdp"] == 20.85
    assert de["debt_gdp_year"] == 1990
    # ...but it is flagged and kept out of the composite and the rank.
    assert de["stale_fields"] == ["debt_gdp"]
    assert de["score"] is None
    assert de["score_missing"] == ["debt_gdp"]
    assert rows["US"]["stale_fields"] == []
    assert rows["US"]["score"] is not None


def test_stale_value_never_wins_a_card(monkeypatch) -> None:
    monkeypatch.setattr(gmm_mod, "_as_of_year", lambda: 2026)
    table: dict[tuple[str, str], dict[str, Any]] = {}
    for ind in ("NY.GDP.MKTP.KD.ZG", "FP.CPI.TOTL.ZG", "SL.UEM.TOTL.ZS", "GC.DOD.TOTL.GD.ZS"):
        table[("US", ind)] = _obs("US", "USA", ind, 2.0, 2025)
    # DE's inflation figure is from 2010: it must not be the "Hottest CPI" card.
    table[("DE", "FP.CPI.TOTL.ZG")] = _obs("DE", "DEU", "FP.CPI.TOTL.ZG", 50.0, 2010)
    _patch_table(monkeypatch, table)

    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["US", "DE"]))
    hottest = next(c for c in result.data["cards"] if c["key"] == "hottest_inflation")
    assert hottest["value"] is not None and "United States" in hottest["value"]
    assert "Germany" not in hottest["value"]


# ── GMM#6: the seed describes the World Bank matrix the handler serves ──


def _gmm_seed():
    from showme.manifest import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    return REGISTRY.get("GMM")


def test_seed_inputs_are_only_the_ones_the_handler_reads() -> None:
    seed = _gmm_seed()
    names = {i.name for i in seed.inputs}
    # The handler reads countries and top_n; provider_mode is never read.
    assert names == {"countries", "top_n"}


def test_seed_describes_world_bank_not_fred_surprises() -> None:
    seed = _gmm_seed()
    assert seed.provider_chain.primary == "worldbank"
    text = " ".join([seed.intent, seed.methodology, " ".join(
        f"{t.name} {' '.join(t.assertions)}" for t in seed.semantic_tests
    )])
    assert "FRED" not in text
    assert "surprise" not in text.lower()
    assert "movers" not in text.lower()


def test_seed_output_contract_names_only_fields_the_handler_serves() -> None:
    seed = _gmm_seed()
    assert seed.output_contract.must_have, "must_have must not be empty"
    for key in ("movers", "window", "data_mode", "as_of"):
        assert key not in seed.output_contract.must_have, key


def test_seed_must_have_keys_present_in_live_payload(monkeypatch) -> None:
    seed = _gmm_seed()
    table: dict[tuple[str, str], dict[str, Any]] = {}
    for ind in INDICATORS:
        table[("US", ind)] = _obs("US", "USA", ind, 2.0, 2025)
    _patch_table(monkeypatch, table)

    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["US"]))
    assert result.data["status"] == "ok"
    for key in seed.output_contract.must_have:
        assert key in result.data, f"must_have {key!r} missing from payload"
        assert result.data[key], f"must_have {key!r} empty for status=ok"


def test_seed_card_and_field_names_match_the_payload(monkeypatch) -> None:
    seed = _gmm_seed()
    table: dict[tuple[str, str], dict[str, Any]] = {}
    for ind in INDICATORS:
        table[("US", ind)] = _obs("US", "USA", ind, 2.0, 2025)
    _patch_table(monkeypatch, table)
    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["US"]))

    card_keys = {c["key"] for c in result.data["cards"]}
    for slot in seed.card_schema.slots:
        assert slot.key in card_keys, f"card slot {slot.key!r} not in payload cards"

    row_keys = set(result.data["rows"][0])
    for col in seed.table_schema.columns:
        assert col.key in row_keys, f"table column {col.key!r} not in row payload"
    for field_name in seed.field_dict:
        assert field_name.startswith("rows[]."), field_name
        base = field_name[len("rows[]."):]
        assert base in row_keys, f"field_dict {field_name!r} not in row payload"


# ── GMM#2: the real World Bank aggregate response ids map to our codes ──


@pytest.mark.parametrize(
    "country_id, iso3, expected",
    [
        ("XC", "EMU", "EZ"),  # World Bank's id for the euro area (iso2 XC, iso3 EMU)
        ("EMU", "", "EZ"),    # the request spelling, if it comes back as the id
        ("EMU", "EMU", "EZ"),
        ("EU", "EUU", "EU"),  # European Union aggregate
        ("EUU", "", "EU"),
    ],
)
def test_worldbank_aggregate_response_ids_map_to_our_codes(
    country_id: str, iso3: str, expected: str,
) -> None:
    payload = [
        {"page": 1, "pages": 1, "total": 1},
        [
            {
                "indicator": {"id": "FP.CPI.TOTL.ZG"},
                "country": {"id": country_id, "value": "aggregate"},
                "countryiso3code": iso3,
                "date": "2025",
                "value": 2.0,
            }
        ],
    ]
    assert set(gmm_mod._parse_wb_series(payload)) == {expected}


# ── GMM#3 follow-up: an empty World Bank response is an explicit empty state ──


def test_all_null_worldbank_response_is_empty_not_ok(monkeypatch) -> None:
    """No observation for any requested country must not present as status ok."""
    _patch_table(monkeypatch, {})

    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["US", "EZ"]))
    assert result.data["status"] == "empty", result.data.get("status")
    assert result.data.get("reason")
    assert result.data.get("next_actions")
    # No country row may carry a value or a score the provider never returned.
    assert result.data["rows"] == [], "an empty matrix must not list empty country rows"


def test_partial_worldbank_response_stays_ok(monkeypatch) -> None:
    """One real observation is enough for an ok matrix; the rest stays null."""
    table = {("US", "FP.CPI.TOTL.ZG"): _obs("US", "USA", "FP.CPI.TOTL.ZG", 3.1, 2025)}
    _patch_table(monkeypatch, table)

    result = _run(GMMFunction(deps=FunctionDeps()).execute(countries=["US", "EZ"]))
    assert result.data["status"] == "ok"
