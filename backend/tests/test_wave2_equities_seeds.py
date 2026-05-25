"""Wave 2 equities-family manifest seeds (22 codes).

Exercises every seed registered via
``backend/showme/manifest/seeds/<code>_seed.py`` for the wave-2 equities
batch. Asserts:

* Each code is registered by ``load_seeds()``.
* Shared shape invariants (category, asset_classes, methodology length,
  semantic tests, provider chain).
* Per-family invariants for SEC-EDGAR backed, yfinance backed, and
  computed/modeled groups.
* Formula contracts for the valuation functions
  (DCF / DDM / WACC / BETA) — the formula_dict MUST encode the core
  textbook formula.
* Output / semantic tests echo MODEL_ASSUMPTIONs for the valuation
  functions (``assumptions_visible_in_output`` assertion).
"""
from __future__ import annotations

import re

import pytest

from showme.manifest import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
    REGISTRY,
    load_seeds,
)


WAVE2_EQUITIES_CODES: tuple[str, ...] = (
    "ANR",
    "APPL",
    "BETA",
    "CACT",
    "DARK",
    "DCF",
    "DCFS",
    "DDM",
    "DPF",
    "DVD",
    "EE",
    "EREV",
    "ESG",
    "FORM4",
    "FTS",
    "HDS",
    "HFS",
    "LITM",
    "PIB",
    "RV",
    "SPLC",
    "WACC",
)


SEC_EDGAR_PRIMARY: frozenset[str] = frozenset(
    {"FORM4", "FTS", "HDS", "HFS", "CACT", "SPLC", "LITM"}
)
YFINANCE_PRIMARY: frozenset[str] = frozenset(
    {"APPL", "PIB", "DPF", "DVD", "ANR", "EE", "EREV", "RV", "DARK"}
)
INTERNAL_PRIMARY: frozenset[str] = frozenset(
    {"BETA", "WACC", "DCF", "DCFS", "DDM", "ESG"}
)
VALUATION_CODES: frozenset[str] = frozenset({"DCF", "DCFS", "DDM", "WACC"})


@pytest.fixture(scope="module", autouse=True)
def _ensure_seeds_loaded() -> None:
    """Import every seed module once so the registry is populated."""
    load_seeds()


# ---------------------------------------------------------------------------
# Registration + shared shape
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", WAVE2_EQUITIES_CODES)
def test_equities_seed_is_registered(code: str) -> None:
    assert code in REGISTRY, f"{code} seed must be registered by load_seeds()"


@pytest.mark.parametrize("code", WAVE2_EQUITIES_CODES)
def test_equities_seed_shape(code: str) -> None:
    """Every equities seed shares the same minimum-quality bar."""
    entry = REGISTRY.get(code)
    assert entry.code == code, f"{code} manifest must declare matching code"
    assert entry.category == Category.EQUITIES, (
        f"{code} must declare category=EQUITIES, got {entry.category}"
    )
    assert AssetClass.EQUITY in entry.asset_classes, (
        f"{code} must declare AssetClass.EQUITY in asset_classes"
    )
    assert entry.inputs, f"{code} must declare at least one input control"
    assert len(entry.methodology) >= 80, (
        f"{code} methodology must explain the model (>= 80 chars), got "
        f"{len(entry.methodology)}"
    )
    assert entry.semantic_tests, f"{code} must declare at least one semantic test"
    assert entry.output_contract.must_have, (
        f"{code}.output_contract.must_have must list at least one required field"
    )
    # Provenance is required for every equities pane.
    assert entry.provenance is not None
    assert entry.provenance.require_source_list is True
    assert entry.provenance.require_as_of is True


# ---------------------------------------------------------------------------
# Provider-family classification
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", sorted(SEC_EDGAR_PRIMARY))
def test_sec_edgar_primary_chain(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.provider_chain.primary == "sec_edgar", (
        f"{code} must declare primary=sec_edgar (SEC-EDGAR-backed group), "
        f"got primary={entry.provider_chain.primary!r}"
    )


@pytest.mark.parametrize("code", sorted(YFINANCE_PRIMARY))
def test_yfinance_primary_chain(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.provider_chain.primary == "yfinance", (
        f"{code} must declare primary=yfinance (yfinance-backed group), "
        f"got primary={entry.provider_chain.primary!r}"
    )


@pytest.mark.parametrize("code", sorted(INTERNAL_PRIMARY))
def test_internal_primary_chain(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.provider_chain.primary == "internal", (
        f"{code} must declare primary=internal (computed/modeled group), "
        f"got primary={entry.provider_chain.primary!r}"
    )


def test_esg_accepts_not_configured_or_cached_only() -> None:
    """ESG has no real vendor — modes must be limited to NOT_CONFIGURED + CACHED_SNAPSHOT."""
    entry = REGISTRY.get("ESG")
    modes = set(entry.provider_chain.acceptable_modes)
    assert modes <= {DataMode.NOT_CONFIGURED, DataMode.CACHED_SNAPSHOT}, (
        f"ESG.acceptable_modes must be a subset of "
        f"{{NOT_CONFIGURED, CACHED_SNAPSHOT}}, got {modes}"
    )
    assert "paid vendor" in entry.methodology.lower(), (
        "ESG methodology must explicitly mention the paid-vendor requirement"
    )


# ---------------------------------------------------------------------------
# Valuation-function formula + assumption contracts
# ---------------------------------------------------------------------------


def test_dcf_formula_dict_includes_core_pv_formula() -> None:
    """DCF must include PV = Σ_t CF_t / (1+r)^t + TV / (1+r)^n."""
    dcf = REGISTRY.get("DCF")
    assert dcf.formula_dict, "DCF must declare formulas in formula_dict"
    blob = " ".join(
        formula.expression + " " + (formula.notes or "")
        for formula in dcf.formula_dict.values()
    )
    # Sum sign + (1+r)^t term + TV / (1+r)^n term.
    assert re.search(r"\\sum.*\\frac\{CF_t\}\{\(1\+r\)\^t\}", blob), (
        "DCF.formula_dict must include the discounted-sum term "
        r"\sum CF_t/(1+r)^t — got "
        f"{blob!r}"
    )
    assert re.search(r"TV.*\(1\+r\)\^n", blob), (
        r"DCF.formula_dict must include the terminal-value discount term TV/(1+r)^n"
    )


def test_ddm_formula_dict_includes_gordon_growth() -> None:
    """DDM must include P_0 = D_1 / (r-g)."""
    ddm = REGISTRY.get("DDM")
    assert ddm.formula_dict, "DDM must declare formulas in formula_dict"
    blob = " ".join(
        formula.expression for formula in ddm.formula_dict.values()
    )
    # Gordon formula: P_0 = D_1 / (r - g)
    assert re.search(r"P_0.*=.*\\frac\{D_1\}\{r\s*-\s*g\}", blob), (
        r"DDM.formula_dict must include the Gordon-growth expression "
        r"P_0 = D_1 / (r - g) — got "
        f"{blob!r}"
    )


def test_wacc_formula_dict_includes_weighted_capital_formula() -> None:
    """WACC must include WACC = (E/V) R_e + (D/V) R_d (1-T)."""
    wacc = REGISTRY.get("WACC")
    assert wacc.formula_dict, "WACC must declare formulas in formula_dict"
    blob = " ".join(
        formula.expression for formula in wacc.formula_dict.values()
    )
    # The full WACC formula with E/V, D/V, (1-T)
    assert re.search(r"WACC\s*=\s*\\frac\{E\}\{V\}.*R_e.*\\frac\{D\}\{V\}.*R_d.*\(1\s*-\s*T\)", blob), (
        r"WACC.formula_dict must include WACC = (E/V) R_e + (D/V) R_d (1 - T) — got "
        f"{blob!r}"
    )


def test_beta_formula_dict_includes_capm_beta() -> None:
    """BETA must include β = Cov(R_i, R_m) / Var(R_m)."""
    beta = REGISTRY.get("BETA")
    assert beta.formula_dict, "BETA must declare formulas in formula_dict"
    blob = " ".join(
        formula.expression for formula in beta.formula_dict.values()
    )
    # CAPM beta: \beta = Cov(R_i, R_m) / Var(R_m)
    assert re.search(r"\\beta\s*=\s*\\frac\{Cov\(R_i,\s*R_m\)\}\{Var\(R_m\)\}", blob), (
        r"BETA.formula_dict must include β = Cov(R_i, R_m) / Var(R_m) — got "
        f"{blob!r}"
    )


@pytest.mark.parametrize("code", sorted(VALUATION_CODES | {"BETA"}))
def test_valuation_inputs_include_model_assumptions(code: str) -> None:
    """DCF/DCFS/DDM/WACC/BETA must expose editable MODEL_ASSUMPTION controls."""
    entry = REGISTRY.get(code)
    assumption_inputs = [
        i for i in entry.inputs if i.control == ControlKind.MODEL_ASSUMPTION
    ]
    assert assumption_inputs, (
        f"{code} must expose at least one MODEL_ASSUMPTION input so the "
        f"valuation can be edited at runtime; got controls "
        f"{[i.control.value for i in entry.inputs]}"
    )


@pytest.mark.parametrize("code", sorted(VALUATION_CODES | {"BETA"}))
def test_valuation_output_must_have_assumptions_field(code: str) -> None:
    """Valuation functions must promise `assumptions` in their output payload."""
    entry = REGISTRY.get(code)
    assert "assumptions" in entry.output_contract.must_have, (
        f"{code}.output_contract.must_have must include 'assumptions' so the "
        f"consumer can audit which model produced the number — got "
        f"{entry.output_contract.must_have}"
    )


@pytest.mark.parametrize("code", sorted(VALUATION_CODES | {"BETA"}))
def test_valuation_semantic_tests_pin_assumptions_visible(code: str) -> None:
    """At least one semantic test must assert assumptions_visible_in_output."""
    entry = REGISTRY.get(code)
    blob = " ".join(
        " ".join(t.assertions) for t in entry.semantic_tests
    )
    assert "assumptions_visible_in_output" in blob, (
        f"{code} must declare a semantic test with the assertion "
        f"'assumptions_visible_in_output' (echoed inputs in output). "
        f"Found assertions: {blob!r}"
    )


# ---------------------------------------------------------------------------
# Per-code exemplar checks
# ---------------------------------------------------------------------------


def test_dcfs_chart_is_heatmap() -> None:
    """DCFS visualises the WACC×terminal-growth grid as a heatmap."""
    dcfs = REGISTRY.get("DCFS")
    assert dcfs.chart_grammar is not None
    assert dcfs.chart_grammar.kind == ChartKind.HEATMAP, (
        "DCFS must render its grid as HEATMAP (not a line chart)"
    )


def test_dvd_handles_etf_class_too() -> None:
    dvd = REGISTRY.get("DVD")
    assert AssetClass.ETF in dvd.asset_classes, (
        "DVD must accept ETF symbols too (ETFs pay distributions)"
    )


def test_form4_table_includes_share_delta_columns() -> None:
    form4 = REGISTRY.get("FORM4")
    assert form4.table_schema is not None
    keys = {col.key for col in form4.table_schema.columns}
    expected = {"shares", "price", "transaction_type", "filer"}
    assert expected.issubset(keys), (
        f"FORM4.table_schema must include core insider columns {expected}, "
        f"got {keys}"
    )


def test_fts_query_input_is_required() -> None:
    fts = REGISTRY.get("FTS")
    query_inputs = [i for i in fts.inputs if i.name == "query"]
    assert query_inputs, "FTS must declare a `query` input"
    assert query_inputs[0].required is True, "FTS query input must be required"


def test_litm_includes_severity_filter() -> None:
    litm = REGISTRY.get("LITM")
    sev_inputs = [i for i in litm.inputs if i.name == "severity"]
    assert sev_inputs, "LITM must expose a severity filter"
    assert sev_inputs[0].options, "LITM severity options must be enumerated"


def test_splc_methodology_warns_approximate() -> None:
    splc = REGISTRY.get("SPLC")
    assert "approximate" in splc.methodology.lower(), (
        "SPLC methodology must call out that supply-chain extraction is approximate"
    )


def test_rv_includes_pe_and_ev_ebitda_columns() -> None:
    rv = REGISTRY.get("RV")
    assert rv.table_schema is not None
    keys = {col.key for col in rv.table_schema.columns}
    assert "pe_ttm" in keys and "ev_ebitda" in keys, (
        f"RV.table_schema must include pe_ttm + ev_ebitda columns, got {keys}"
    )


def test_wacc_card_exposes_components() -> None:
    wacc = REGISTRY.get("WACC")
    assert wacc.card_schema is not None
    keys = {slot.key for slot in wacc.card_schema.slots}
    expected = {"wacc", "re_capm", "rd", "beta", "equity_weight", "debt_weight"}
    assert expected.issubset(keys), (
        f"WACC.card_schema must surface the component KPIs {expected}, got {keys}"
    )
