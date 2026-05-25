"""Wave 2 macro + news/intel manifest seeds.

Covers the 17-code MACRO + NEWS_INTEL block:
  MACRO     : COUN, ECFC, GMM, REGM, TRDH
  NEWS_INTEL: AV, BRIEF, EVTS, NALRT, NI, NSE, READ, SOSC, TLDR, TRAN, TRQA, TSAR

Tests every seed registers via load_seeds(), passes the shared
shape-quality bar, and honours the spec's per-code semantic invariants:

  * ECFC must declare a `vintage_visible_in_payload` semantic test.
  * GMM must render as a bar_ladder chart and use FRED as primary.
  * REGM must lead with the internal model and expose at least one
    `model_assumption` control input.
  * TRDH must declare no chart grammar (table-only) and use `internal`
    as primary (curated calendar).
  * AV methodology must mention "playable archive" — not a placeholder list.
  * BRIEF must declare an `evidence_links_present` semantic test.
  * NI must declare an `impact_is_a_tag` style test asserting impact is
    a tag bucket (low/medium/high), not a synthetic float.
  * SOSC must declare a `composite_sources_listed_in_payload` test.
  * TLDR must declare an `every_bullet_has_evidence_link` test (must
    cite evidence — no synthetic prose).
  * TRAN / TRQA / TSAR (Whisper-gated) must include NOT_CONFIGURED in
    their acceptable_modes and the methodology must mention Whisper.
"""
from __future__ import annotations

import re

import pytest

from showme.manifest import REGISTRY, Category, ChartKind, ControlKind, DataMode, load_seeds


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------


MACRO_CODES = ("COUN", "ECFC", "GMM", "REGM", "TRDH")
NEWS_INTEL_CODES = (
    "AV",
    "BRIEF",
    "EVTS",
    "NALRT",
    "NI",
    "NSE",
    "READ",
    "SOSC",
    "TLDR",
    "TRAN",
    "TRQA",
    "TSAR",
)
ALL_CODES = MACRO_CODES + NEWS_INTEL_CODES

WHISPER_GATED_CODES = ("TRAN", "TRQA", "TSAR")


# ---------------------------------------------------------------------------
# Fixture: load every seed module once per test module
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module", autouse=True)
def _load_all_seeds() -> None:
    load_seeds()


# ---------------------------------------------------------------------------
# Registration + shared shape checks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ALL_CODES)
def test_seed_is_registered(code: str) -> None:
    """Every Wave-2 macro/news code is in the registry after load_seeds()."""
    assert code in REGISTRY, f"manifest {code!r} not registered"
    entry = REGISTRY.get(code)
    assert entry.code == code, f"registered code {entry.code!r} != {code!r}"


@pytest.mark.parametrize("code", ALL_CODES)
def test_seed_shape_is_sane(code: str) -> None:
    """Inputs non-empty, methodology substantial, semantic_tests non-empty."""
    entry = REGISTRY.get(code)
    assert entry.inputs, f"{code} must declare at least one input"
    assert len(entry.methodology) >= 50, (
        f"{code} methodology must be substantial (>=50 chars), "
        f"got {len(entry.methodology)}"
    )
    assert entry.semantic_tests, f"{code} must declare at least one semantic test"
    assert entry.output_contract.must_have, (
        f"{code} output_contract.must_have must list at least one promised field"
    )


@pytest.mark.parametrize("code", MACRO_CODES)
def test_macro_seed_category_is_macro(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.category == Category.MACRO, (
        f"{code} must declare category=MACRO, got {entry.category!r}"
    )


@pytest.mark.parametrize("code", NEWS_INTEL_CODES)
def test_news_intel_seed_category_is_news_intel(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.category == Category.NEWS_INTEL, (
        f"{code} must declare category=NEWS_INTEL, got {entry.category!r}"
    )


# ---------------------------------------------------------------------------
# MACRO per-code exemplars
# ---------------------------------------------------------------------------


def test_ecfc_vintage_visible_in_payload_test_declared() -> None:
    """ECFC must pin that the forecast vintage is visible in the response payload."""
    ecfc = REGISTRY.get("ECFC")
    test_names = [t.name for t in ecfc.semantic_tests]
    assert any("vintage_visible_in_payload" in name for name in test_names), (
        "ECFC must declare a semantic_test whose name contains "
        f"'vintage_visible_in_payload'; got {test_names!r}"
    )


def test_gmm_chart_is_bar_ladder() -> None:
    """GMM ranks surprises as a diverging strike ladder."""
    gmm = REGISTRY.get("GMM")
    assert gmm.chart_grammar is not None, "GMM must declare a chart grammar"
    assert gmm.chart_grammar.kind == ChartKind.BAR_LADDER, (
        f"GMM.chart_grammar.kind must be BAR_LADDER, got {gmm.chart_grammar.kind!r}"
    )


def test_gmm_primary_provider_is_fred() -> None:
    gmm = REGISTRY.get("GMM")
    assert gmm.provider_chain.primary == "fred", (
        f"GMM primary provider must be 'fred', got {gmm.provider_chain.primary!r}"
    )


def test_coun_primary_provider_is_fred() -> None:
    coun = REGISTRY.get("COUN")
    assert coun.provider_chain.primary == "fred", (
        f"COUN primary provider must be 'fred', got {coun.provider_chain.primary!r}"
    )


def test_regm_primary_provider_is_internal_with_model_assumption_input() -> None:
    """REGM is the internal regime classifier — model-driven with transparent assumptions."""
    regm = REGISTRY.get("REGM")
    assert regm.provider_chain.primary == "internal", (
        f"REGM primary must be 'internal', got {regm.provider_chain.primary!r}"
    )
    assumption_inputs = [i for i in regm.inputs if i.control == ControlKind.MODEL_ASSUMPTION]
    assert assumption_inputs, (
        "REGM must expose at least one model_assumption input (regime features / threshold)"
    )


def test_trdh_is_table_only_and_internal() -> None:
    """TRDH is a curated calendar; no chart, primary is internal."""
    trdh = REGISTRY.get("TRDH")
    assert trdh.chart_grammar is None, (
        "TRDH must declare no chart_grammar (table-only)"
    )
    assert trdh.provider_chain.primary == "internal", (
        f"TRDH primary must be 'internal' (curated calendar), "
        f"got {trdh.provider_chain.primary!r}"
    )


# ---------------------------------------------------------------------------
# NEWS_INTEL per-code exemplars
# ---------------------------------------------------------------------------


def test_av_methodology_mentions_playable_archive() -> None:
    """AV is a playable archive, never a placeholder list."""
    av = REGISTRY.get("AV")
    assert "playable archive" in av.methodology.lower(), (
        "AV.methodology must mention 'playable archive' to distinguish it from "
        "a placeholder list"
    )


def test_brief_evidence_links_present_test_declared() -> None:
    """BRIEF must pin that every bullet cites evidence."""
    brief = REGISTRY.get("BRIEF")
    test_names = [t.name for t in brief.semantic_tests]
    assert any("evidence_links_present" in name for name in test_names), (
        "BRIEF must declare a semantic_test whose name contains "
        f"'evidence_links_present'; got {test_names!r}"
    )


def test_ni_impact_is_a_tag_not_float() -> None:
    """NI's `impact` field must be tag-bucketed (low/medium/high), not a float."""
    ni = REGISTRY.get("NI")
    test_names = [t.name for t in ni.semantic_tests]
    assert any("impact_is_a_tag" in name for name in test_names), (
        "NI must declare a semantic_test whose name contains "
        f"'impact_is_a_tag'; got {test_names!r}"
    )


def test_ni_impact_field_dict_declares_tag_not_float() -> None:
    """NI field_dict must describe `impact` as a tag, not a numeric score."""
    ni = REGISTRY.get("NI")
    impact_field = ni.field_dict.get("items[].impact")
    assert impact_field is not None, (
        "NI.field_dict must declare items[].impact (the tag bucket)"
    )
    desc_blob = (impact_field.description or "").lower()
    assert any(token in desc_blob for token in ("tag", "low", "medium", "high")), (
        f"NI items[].impact description must describe it as a tag bucket; "
        f"got {impact_field.description!r}"
    )


def test_sosc_composite_sources_listed_in_payload_test_declared() -> None:
    """SOSC's composite must always list its contributing sources."""
    sosc = REGISTRY.get("SOSC")
    test_names = [t.name for t in sosc.semantic_tests]
    assert any("composite_sources_listed_in_payload" in name for name in test_names), (
        "SOSC must declare a semantic_test whose name contains "
        f"'composite_sources_listed_in_payload'; got {test_names!r}"
    )


def test_tldr_cites_evidence_in_semantic_tests() -> None:
    """TLDR must assert every bullet has an evidence link — no synthetic summaries."""
    tldr = REGISTRY.get("TLDR")
    test_names = [t.name for t in tldr.semantic_tests]
    matched = [n for n in test_names if "evidence" in n]
    assert matched, (
        "TLDR must declare at least one semantic_test pinning the "
        f"'every bullet cites evidence' contract; got {test_names!r}"
    )


@pytest.mark.parametrize("code", WHISPER_GATED_CODES)
def test_whisper_gated_seed_accepts_not_configured_mode(code: str) -> None:
    """TRAN/TRQA/TSAR must declare NOT_CONFIGURED as an acceptable mode."""
    entry = REGISTRY.get(code)
    assert DataMode.NOT_CONFIGURED in entry.provider_chain.acceptable_modes, (
        f"{code} must accept DataMode.NOT_CONFIGURED so the response can honestly "
        f"say Whisper isn't wired up; "
        f"got acceptable_modes={entry.provider_chain.acceptable_modes!r}"
    )


@pytest.mark.parametrize("code", WHISPER_GATED_CODES)
def test_whisper_gated_seed_methodology_mentions_whisper(code: str) -> None:
    """TRAN/TRQA/TSAR must mention Whisper in their methodology."""
    entry = REGISTRY.get(code)
    assert re.search(r"whisper", entry.methodology, re.IGNORECASE), (
        f"{code}.methodology must mention 'Whisper' — full audio transcripts "
        f"require it"
    )


# ---------------------------------------------------------------------------
# Cross-cutting guarantees
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ALL_CODES)
def test_every_input_has_a_description(code: str) -> None:
    """Every input control must explain what it does (audit pass)."""
    entry = REGISTRY.get(code)
    for input_spec in entry.inputs:
        assert input_spec.description, (
            f"{code} input {input_spec.name!r} must declare a non-empty description"
        )


@pytest.mark.parametrize("code", ALL_CODES)
def test_provenance_requires_source_list_and_as_of(code: str) -> None:
    """No seed in this block may suppress source / as_of provenance."""
    entry = REGISTRY.get(code)
    assert entry.provenance.require_source_list is True, (
        f"{code} must require a source_list in the response"
    )
    assert entry.provenance.require_as_of is True, (
        f"{code} must require an as_of timestamp"
    )
