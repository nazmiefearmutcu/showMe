"""Wave-2 SCREENING-family manifest seeds.

Covers the thirteen screening codes (CSRC, EQS, FRH, FSRC, ICX, MAP,
MICRO, MOSS, MOST, SECF, SECT, SRCH, WEI) registered via
``backend/showme/manifest/seeds/<code>_seed.py``. Asserts schema-shape
invariants every seed must honor plus the per-code chart-grammar
exemplars called out in the rebuild contract:

* WEI  → bar_ladder (ranked horizontal indices, NOT a row-index line)
* MAP  → heatmap (treemap is conceptually heatmap)
* SECT → bar_ladder
* MOST → bar_ladder
* MOSS → bar_ladder
* FRH  → heatmap (NOT row-index; wave2 spec mandates it)
* MICRO must declare an ``explicit_unavailable_when_no_depth_provider`` test
* FRH   must declare an ``frh_chart_grammar_is_heatmap`` test
"""
from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, Category, ChartKind, load_seeds


SCREENING_CODES = (
    "CSRC",
    "EQS",
    "FRH",
    "FSRC",
    "ICX",
    "MAP",
    "MICRO",
    "MOSS",
    "MOST",
    "SECF",
    "SECT",
    "SRCH",
    "WEI",
)

# Providers permitted as the primary in this family. Mirrors the
# wave-1 floor sets and the spec table in the wave-2 brief.
ALLOWED_PRIMARY_PROVIDERS = frozenset(
    {
        "yfinance",
        "binance",
        "openfigi",
        "coingecko",
        "cached_snapshot",
    }
)


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    """Populate REGISTRY before any wave-2 screening test runs."""
    load_seeds()


# ---------------------------------------------------------------------------
# Registration + shape floor
# ---------------------------------------------------------------------------


def test_every_screening_code_is_registered() -> None:
    """Every wave-2 screening code must be in the registry after load_seeds()."""
    codes = set(REGISTRY.codes())
    missing = [c for c in SCREENING_CODES if c not in codes]
    assert not missing, f"wave-2 screening seeds not registered: {missing}"


@pytest.mark.parametrize("code", SCREENING_CODES)
def test_screening_seed_registered_with_basic_shape(code: str) -> None:
    """Every wave-2 screening seed shares the same minimum-quality bar."""
    entry = REGISTRY.get(code)
    assert entry.code == code, f"{code}: registered manifest reports a different code"
    assert entry.category == Category.SCREENING, (
        f"{code}: category must be Category.SCREENING, got {entry.category!r}"
    )
    assert entry.inputs, f"{code}: inputs must be non-empty"
    assert len(entry.methodology) >= 50, (
        f"{code}: methodology must be at least 50 chars (got {len(entry.methodology)})"
    )
    assert entry.semantic_tests, f"{code}: semantic_tests must be non-empty"
    assert entry.provider_chain.primary in ALLOWED_PRIMARY_PROVIDERS, (
        f"{code}: provider_chain.primary={entry.provider_chain.primary!r} not in "
        f"the allowed set {ALLOWED_PRIMARY_PROVIDERS}"
    )


@pytest.mark.parametrize("code", SCREENING_CODES)
def test_screening_seed_promises_next_actions(code: str) -> None:
    """All screening codes ship saved-screen / export / open-in-GP next_actions."""
    entry = REGISTRY.get(code)
    assert entry.output_contract.next_actions is True, (
        f"{code}: output_contract.next_actions must be True so the UI gets "
        "save-screen / export / open-in-GP affordances"
    )


# ---------------------------------------------------------------------------
# Per-code chart-grammar assertions
# ---------------------------------------------------------------------------


def test_wei_chart_grammar_is_bar_ladder() -> None:
    """WEI must render ranked indices as bar_ladder, NOT a row-index line."""
    entry = REGISTRY.get("WEI")
    assert entry.chart_grammar is not None, "WEI must declare a chart grammar"
    assert entry.chart_grammar.kind == ChartKind.BAR_LADDER, (
        f"WEI.chart_grammar.kind must be bar_ladder, got {entry.chart_grammar.kind!r}"
    )


def test_map_chart_grammar_is_heatmap() -> None:
    """MAP renders a treemap — conceptually a heatmap per the wave2 contract."""
    entry = REGISTRY.get("MAP")
    assert entry.chart_grammar is not None, "MAP must declare a chart grammar"
    assert entry.chart_grammar.kind == ChartKind.HEATMAP, (
        f"MAP.chart_grammar.kind must be heatmap, got {entry.chart_grammar.kind!r}"
    )


def test_frh_chart_grammar_is_heatmap() -> None:
    """FRH funding rate must visualise as heatmap, NOT a row-index series.

    Wave-2 spec is explicit: this is the exemplar that pins HEATMAP for
    the funding-rate matrix output.
    """
    entry = REGISTRY.get("FRH")
    assert entry.chart_grammar is not None, "FRH must declare a chart grammar"
    assert entry.chart_grammar.kind == ChartKind.HEATMAP, (
        f"FRH.chart_grammar.kind must be heatmap, got {entry.chart_grammar.kind!r}"
    )


def test_sect_chart_grammar_is_bar_ladder() -> None:
    """SECT sector rotation renders as ranked bar ladder."""
    entry = REGISTRY.get("SECT")
    assert entry.chart_grammar is not None, "SECT must declare a chart grammar"
    assert entry.chart_grammar.kind == ChartKind.BAR_LADDER, (
        f"SECT.chart_grammar.kind must be bar_ladder, got {entry.chart_grammar.kind!r}"
    )


def test_most_chart_grammar_is_bar_ladder() -> None:
    """MOST top movers renders as ranked bar ladder."""
    entry = REGISTRY.get("MOST")
    assert entry.chart_grammar is not None, "MOST must declare a chart grammar"
    assert entry.chart_grammar.kind == ChartKind.BAR_LADDER, (
        f"MOST.chart_grammar.kind must be bar_ladder, got {entry.chart_grammar.kind!r}"
    )


def test_moss_chart_grammar_is_bar_ladder() -> None:
    """MOSS sectoral movers renders as side-by-side ranked bar ladders."""
    entry = REGISTRY.get("MOSS")
    assert entry.chart_grammar is not None, "MOSS must declare a chart grammar"
    assert entry.chart_grammar.kind == ChartKind.BAR_LADDER, (
        f"MOSS.chart_grammar.kind must be bar_ladder, got {entry.chart_grammar.kind!r}"
    )


# ---------------------------------------------------------------------------
# Per-code semantic-test name exemplars
# ---------------------------------------------------------------------------


def test_micro_declares_explicit_unavailable_when_no_depth_provider_test() -> None:
    """MICRO must pin the explicit-unavailable-on-no-depth-provider invariant.

    Only Binance in our adapter list exposes a real L2 depth feed. For every
    other asset class MICRO must surface as explicit_unavailable rather than
    paint a synthesized ladder.
    """
    micro = REGISTRY.get("MICRO")
    test_names = [t.name for t in micro.semantic_tests]
    assert any(
        "explicit_unavailable_when_no_depth_provider" in name for name in test_names
    ), (
        "MICRO must declare a semantic_test whose name contains "
        f"'explicit_unavailable_when_no_depth_provider'; got {test_names!r}"
    )


def test_frh_declares_chart_grammar_is_heatmap_test() -> None:
    """FRH must declare the chart-grammar-is-heatmap semantic test name."""
    frh = REGISTRY.get("FRH")
    test_names = [t.name for t in frh.semantic_tests]
    assert any("frh_chart_grammar_is_heatmap" == name for name in test_names), (
        "FRH must declare a semantic_test exactly named "
        f"'frh_chart_grammar_is_heatmap'; got {test_names!r}"
    )


# ---------------------------------------------------------------------------
# Provider-routing exemplars
# ---------------------------------------------------------------------------


def test_csrc_primary_provider_is_binance() -> None:
    """CSRC is the crypto screener — primary must be binance for live ticker."""
    csrc = REGISTRY.get("CSRC")
    assert csrc.provider_chain.primary == "binance", (
        f"CSRC primary provider must be 'binance'; got {csrc.provider_chain.primary!r}"
    )


def test_frh_primary_provider_is_binance() -> None:
    """FRH funding rates come from Binance futures."""
    frh = REGISTRY.get("FRH")
    assert frh.provider_chain.primary == "binance", (
        f"FRH primary provider must be 'binance'; got {frh.provider_chain.primary!r}"
    )


def test_secf_and_srch_primary_provider_is_openfigi() -> None:
    """SECF and SRCH route security lookups through OpenFIGI."""
    for code in ("SECF", "SRCH"):
        entry = REGISTRY.get(code)
        assert entry.provider_chain.primary == "openfigi", (
            f"{code} primary provider must be 'openfigi'; "
            f"got {entry.provider_chain.primary!r}"
        )


def test_micro_primary_provider_is_binance() -> None:
    """Only Binance exposes a real L2 depth feed in our adapter list."""
    micro = REGISTRY.get("MICRO")
    assert micro.provider_chain.primary == "binance", (
        f"MICRO primary provider must be 'binance'; "
        f"got {micro.provider_chain.primary!r}"
    )
