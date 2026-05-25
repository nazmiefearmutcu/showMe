"""Wave 2 manifest seeds: BONDS_RATES + CHARTS_TECH + COMMS_PEOPLE.

Covers every code in the wave-2 batch:
    ALLQ, CRPR, CRVF, DDIS, DEBT, GC3D, SRSK, TAUC, WB, YAS,
    CHGS, TECH, MEET, PEOP

Asserts:
    * each is registered after ``load_seeds()``
    * each meets the contract floor (inputs, methodology, semantic tests,
      known primary provider, valid category)
    * the spec-mandated special semantic tests are present:
        - CRVF declares ``tenor_curve_not_row_index``
        - TECH declares a ``studies`` multiselect input
        - PEOP and MEET each declare a ``people_directory_results_have_profile_cards``
          semantic test
    * each category lands on the right ``Category`` enum
"""
from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, load_seeds
from showme.manifest.enums import Category, ChartKind, ControlKind


WAVE2_BOND_CODES = (
    "ALLQ",
    "CRPR",
    "CRVF",
    "DDIS",
    "DEBT",
    "GC3D",
    "SRSK",
    "TAUC",
    "WB",
    "YAS",
)
WAVE2_CHART_CODES = ("CHGS", "TECH")
WAVE2_COMMS_CODES = ("MEET", "PEOP")
WAVE2_ALL_CODES = WAVE2_BOND_CODES + WAVE2_CHART_CODES + WAVE2_COMMS_CODES


# Known primary providers used across the registry (mirrors the wave-1 floor).
# Includes "internal" for orchestrating / directory functions and "ccxt_broker"
# / "cboe_options" / "fx_vol_otc" which already appear in earlier waves.
KNOWN_PRIMARY_PROVIDERS = frozenset(
    {
        "sec_edgar",
        "fred",
        "treasury_direct",
        "openfigi",
        "binance",
        "yfinance",
        "gdelt",
        "rss",
        "internal",
        "ccxt_broker",
        "cboe_options",
        "fx_vol_otc",
    },
)


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    """Populate REGISTRY before any wave-2 test runs."""
    load_seeds()


# ---------------------------------------------------------------------------
# Registration + shape floor
# ---------------------------------------------------------------------------


def test_every_wave2_code_is_registered() -> None:
    """Every wave-2 code must be in the registry after auto-discovery."""
    codes = set(REGISTRY.codes())
    missing = [c for c in WAVE2_ALL_CODES if c not in codes]
    assert not missing, f"wave-2 manifest seeds not registered: {missing}"


@pytest.mark.parametrize("code", WAVE2_ALL_CODES)
def test_wave2_manifest_meets_floor(code: str) -> None:
    """Inputs non-empty, methodology ≥50 chars, semantic_tests non-empty, code matches."""
    entry = REGISTRY.get(code)
    assert entry.code == code, f"{code}: manifest.code mismatch ({entry.code!r})"
    assert entry.inputs, f"{code}: inputs must be non-empty"
    assert entry.semantic_tests, f"{code}: semantic_tests must be non-empty"
    assert len(entry.methodology) >= 50, (
        f"{code}: methodology must be at least 50 chars (got {len(entry.methodology)})"
    )


@pytest.mark.parametrize("code", WAVE2_ALL_CODES)
def test_wave2_primary_provider_is_known(code: str) -> None:
    """Primary provider must be in the curated set so the chain is wirable."""
    entry = REGISTRY.get(code)
    primary = entry.provider_chain.primary
    assert primary in KNOWN_PRIMARY_PROVIDERS, (
        f"{code}: provider_chain.primary={primary!r} is not in the known set"
    )


@pytest.mark.parametrize("code", WAVE2_ALL_CODES)
def test_wave2_provenance_pins_audit_fields(code: str) -> None:
    """Every wave-2 function must require source list + as_of + latency_ms."""
    entry = REGISTRY.get(code)
    assert entry.provenance.require_source_list is True, f"{code}: provenance.require_source_list must be True"
    assert entry.provenance.require_as_of is True, f"{code}: provenance.require_as_of must be True"
    assert entry.provenance.require_latency_ms is True, f"{code}: provenance.require_latency_ms must be True"


@pytest.mark.parametrize("code", WAVE2_ALL_CODES)
def test_wave2_output_contract_has_must_have(code: str) -> None:
    """Every wave-2 manifest declares at least one must_have field."""
    entry = REGISTRY.get(code)
    assert entry.output_contract.must_have, f"{code}: output_contract.must_have must be non-empty"


# ---------------------------------------------------------------------------
# Category placement
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", WAVE2_BOND_CODES)
def test_bond_codes_are_bonds_rates_category(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.category is Category.BONDS_RATES, (
        f"{code} must be Category.BONDS_RATES (got {entry.category!r})"
    )


@pytest.mark.parametrize("code", WAVE2_CHART_CODES)
def test_chart_codes_are_charts_tech_category(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.category is Category.CHARTS_TECH, (
        f"{code} must be Category.CHARTS_TECH (got {entry.category!r})"
    )


@pytest.mark.parametrize("code", WAVE2_COMMS_CODES)
def test_comms_codes_are_comms_people_category(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.category is Category.COMMS_PEOPLE, (
        f"{code} must be Category.COMMS_PEOPLE (got {entry.category!r})"
    )


# ---------------------------------------------------------------------------
# Spec-mandated special semantic tests
# ---------------------------------------------------------------------------


def test_crvf_declares_tenor_curve_not_row_index_test() -> None:
    """CRVF must pin the tenor-on-x-axis invariant via a named semantic test."""
    crvf = REGISTRY.get("CRVF")
    test_names = [t.name for t in crvf.semantic_tests]
    assertions = [a for t in crvf.semantic_tests for a in t.assertions]
    assert any("tenor_curve_not_row_index" in n or "tenor_curve_not_row_index" in a
               for n, a in zip(test_names + assertions, test_names + assertions)) or \
           any("tenor_curve_not_row_index" in a for a in assertions), (
        f"CRVF must declare a semantic test mentioning 'tenor_curve_not_row_index'; "
        f"got names={test_names!r} assertions={assertions!r}"
    )


def test_crvf_chart_grammar_is_tenor_curve() -> None:
    """CRVF must use ChartKind.TENOR_CURVE so the renderer cannot regress to row-index."""
    crvf = REGISTRY.get("CRVF")
    assert crvf.chart_grammar is not None, "CRVF must have a chart_grammar"
    assert crvf.chart_grammar.kind is ChartKind.TENOR_CURVE, (
        f"CRVF chart_grammar.kind must be TENOR_CURVE (got {crvf.chart_grammar.kind!r})"
    )
    assert crvf.chart_grammar.x_axis.unit == "years", (
        f"CRVF x-axis unit must be 'years' (got {crvf.chart_grammar.x_axis.unit!r})"
    )


def test_tech_declares_studies_multiselect_input() -> None:
    """TECH must expose a 'studies' multiselect so the indicator lab is UI-driven."""
    tech = REGISTRY.get("TECH")
    studies = next((i for i in tech.inputs if i.name == "studies"), None)
    assert studies is not None, (
        f"TECH must declare an input named 'studies'; got "
        f"{[i.name for i in tech.inputs]!r}"
    )
    assert studies.control is ControlKind.MULTISELECT, (
        f"TECH studies input must be MULTISELECT (got {studies.control!r})"
    )
    assert studies.options, "TECH studies input must declare options"


def test_peop_semantic_tests_mention_profile_cards() -> None:
    """PEOP must pin 'people directory results have profile cards' in a semantic test."""
    peop = REGISTRY.get("PEOP")
    test_names = [t.name for t in peop.semantic_tests]
    descriptions = [t.description for t in peop.semantic_tests]
    haystack = " | ".join(test_names + descriptions).lower()
    assert "people directory results have profile cards" in haystack or \
           "profile_cards" in haystack or \
           "profile cards" in haystack, (
        f"PEOP must declare a semantic test mentioning 'people directory results have profile cards'; "
        f"got names={test_names!r}"
    )


def test_meet_semantic_tests_mention_profile_cards() -> None:
    """MEET must pin 'people directory results have profile cards' in a semantic test."""
    meet = REGISTRY.get("MEET")
    test_names = [t.name for t in meet.semantic_tests]
    descriptions = [t.description for t in meet.semantic_tests]
    haystack = " | ".join(test_names + descriptions).lower()
    assert "people directory results have profile cards" in haystack or \
           "profile_cards" in haystack or \
           "profile cards" in haystack, (
        f"MEET must declare a semantic test mentioning 'people directory results have profile cards'; "
        f"got names={test_names!r}"
    )


# ---------------------------------------------------------------------------
# Chart-grammar sanity for the bond/chart codes the spec calls out
# ---------------------------------------------------------------------------


def test_gc3d_chart_grammar_is_surface() -> None:
    gc3d = REGISTRY.get("GC3D")
    assert gc3d.chart_grammar is not None
    assert gc3d.chart_grammar.kind is ChartKind.SURFACE


def test_ddis_chart_grammar_is_bar_ladder() -> None:
    ddis = REGISTRY.get("DDIS")
    assert ddis.chart_grammar is not None
    assert ddis.chart_grammar.kind is ChartKind.BAR_LADDER


def test_tauc_has_no_chart_grammar() -> None:
    """TAUC is a calendar table; chart_grammar must be None per the spec note."""
    tauc = REGISTRY.get("TAUC")
    assert tauc.chart_grammar is None, "TAUC chart_grammar must be None (calendar table)"


def test_tech_chart_grammar_is_time_series_candles_multi_pane() -> None:
    tech = REGISTRY.get("TECH")
    assert tech.chart_grammar is not None
    assert tech.chart_grammar.kind is ChartKind.TIME_SERIES_CANDLES
    assert len(tech.chart_grammar.panes) >= 2, "TECH must declare multiple panes (price + studies)"
    pane_names = {p.name for p in tech.chart_grammar.panes}
    assert "price" in pane_names, "TECH must declare a price pane"


def test_yas_uses_bar_ladder_or_no_chart() -> None:
    """YAS chart_grammar must be bar_ladder (spec allows none, but ours uses bar_ladder)."""
    yas = REGISTRY.get("YAS")
    if yas.chart_grammar is not None:
        assert yas.chart_grammar.kind is ChartKind.BAR_LADDER, (
            f"YAS chart_grammar.kind must be BAR_LADDER or None (got {yas.chart_grammar.kind!r})"
        )


# ---------------------------------------------------------------------------
# Spec wiring: TAUC primary is treasury_direct, GC3D/CRVF/WB/SRSK/DEBT use fred
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code,expected_primary", [
    ("TAUC", "treasury_direct"),
    ("CRVF", "fred"),
    ("GC3D", "fred"),
    ("WB", "fred"),
    ("SRSK", "fred"),
    ("DEBT", "fred"),
    ("CRPR", "internal"),
    ("ALLQ", "internal"),
    ("PEOP", "internal"),
    ("MEET", "internal"),
    ("DDIS", "sec_edgar"),
    ("TECH", "yfinance"),
    ("CHGS", "yfinance"),
    ("YAS", "fred"),
])
def test_wave2_primary_provider_assignment(code: str, expected_primary: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.provider_chain.primary == expected_primary, (
        f"{code}: provider_chain.primary must be {expected_primary!r} (got {entry.provider_chain.primary!r})"
    )
