"""Wave 1 derivatives-family manifest seeds.

Exercises the five derivatives seeds (GEX, IVOL, OMON, OVDV, HVT)
registered via ``backend/showme/manifest/seeds/<code>_seed.py``. Asserts
schema-shape invariants every seed must honor plus the per-code
exemplars called out in the rebuild contract:

* GEX → strike-ladder bar chart (``chart_grammar.kind == BAR_LADDER``)
* IVOL → vol surface/heatmap (NOT a row-index plot)
* HVT → ships at least one of Parkinson / Garman-Klass / Yang-Zhang
* OMON → real option-chain columns (bid/ask/iv/Greeks)
"""
from __future__ import annotations

import re

import pytest

from showme.manifest import REGISTRY, ChartKind, load_seeds


DERIVATIVE_CODES = ("GEX", "IVOL", "OMON", "OVDV", "HVT")


@pytest.fixture(scope="module", autouse=True)
def _ensure_seeds_loaded() -> None:
    """Make sure every seed module is imported once for the suite."""
    load_seeds()


@pytest.mark.parametrize("code", DERIVATIVE_CODES)
def test_derivative_seed_is_registered(code: str) -> None:
    assert code in REGISTRY, f"{code} seed must be registered by load_seeds()"


@pytest.mark.parametrize("code", DERIVATIVE_CODES)
def test_derivative_seed_shape(code: str) -> None:
    """Every derivatives seed shares the same minimum-quality bar."""
    entry = REGISTRY.get(code)
    assert entry.code == code, f"{code} manifest must declare matching code"
    assert entry.inputs, f"{code} must declare at least one input control"
    assert len(entry.methodology) >= 50, (
        f"{code} methodology must explain the model (>= 50 chars), got "
        f"{len(entry.methodology)}"
    )
    assert entry.semantic_tests, f"{code} must declare at least one semantic test"


# ---------------------------------------------------------------------------
# Per-code exemplars
# ---------------------------------------------------------------------------


def test_gex_chart_is_bar_ladder() -> None:
    """GEX user-visible exemplar is the diverging strike ladder."""
    gex = REGISTRY.get("GEX")
    assert gex.chart_grammar is not None
    assert gex.chart_grammar.kind == ChartKind.BAR_LADDER, (
        "GEX must render as a bar_ladder (strike ladder vs row-index plot)"
    )


def test_ivol_chart_is_surface_or_heatmap() -> None:
    """IVOL must visualise the vol surface, not a row-index line."""
    ivol = REGISTRY.get("IVOL")
    assert ivol.chart_grammar is not None
    assert ivol.chart_grammar.kind in (ChartKind.SURFACE, ChartKind.HEATMAP), (
        "IVOL must render the vol surface as SURFACE or HEATMAP, got "
        f"{ivol.chart_grammar.kind}"
    )


def test_hvt_formula_dict_ships_realized_vol_estimator() -> None:
    """HVT must ship at least one of Parkinson / Garman-Klass / Yang-Zhang."""
    hvt = REGISTRY.get("HVT")
    assert hvt.formula_dict, "HVT must declare formulas in formula_dict"
    expression_blob = " ".join(
        formula.expression + " " + (formula.notes or "")
        for formula in hvt.formula_dict.values()
    )
    pattern = re.compile(r"Parkinson|Garman|Yang", re.IGNORECASE)
    assert pattern.search(expression_blob), (
        "HVT.formula_dict must mention Parkinson, Garman, or Yang in at least "
        "one formula expression or notes — found none."
    )


def test_omon_table_columns_include_real_option_chain_keys() -> None:
    """OMON must expose at least one canonical option-chain column."""
    omon = REGISTRY.get("OMON")
    assert omon.table_schema is not None, "OMON must declare a table_schema"
    pattern = re.compile(r"^(bid|ask|iv|delta|gamma|vega|theta)$", re.IGNORECASE)
    matched = [col for col in omon.table_schema.columns if pattern.match(col.key)]
    assert matched, (
        "OMON.table_schema.columns must include at least one column whose key "
        "matches /^bid|ask|iv|delta|gamma|vega|theta$/i — got "
        f"{[c.key for c in omon.table_schema.columns]}"
    )
