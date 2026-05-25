"""Wave-1 contract tests for the portfolio + risk seed family.

Covers PORT, ACCT, CORR, PORT_OPT, BLAK. Asserts each is registered with
the right shape and pins the chart-grammar promises that the rebuild
treats as load-bearing (heatmap for CORR, frontier for PORT_OPT, and
at-least-one model_assumption input on BLAK).
"""
from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, ChartKind, ControlKind, load_seeds


PORTFOLIO_CODES = ("PORT", "ACCT", "CORR", "PORT_OPT", "BLAK")

# Providers permitted as the primary in this family. ccxt_broker is the
# placeholder for broker-backed flows (PORT, ACCT); the others cover the
# market-data-backed analytical seeds.
ALLOWED_PRIMARY_PROVIDERS = {
    "ccxt_broker",
    "yfinance",
    "binance",
    "fred",
    "treasury_direct",
    "sec_edgar",
}


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    load_seeds()


@pytest.mark.parametrize("code", PORTFOLIO_CODES)
def test_portfolio_seed_registered_with_basic_shape(code: str) -> None:
    entry = REGISTRY.get(code)
    assert entry.code == code, f"{code}: registered manifest reports a different code"
    assert entry.inputs, f"{code}: inputs must be non-empty"
    assert len(entry.methodology) >= 50, (
        f"{code}: methodology must be at least 50 chars, got {len(entry.methodology)}"
    )
    assert entry.semantic_tests, f"{code}: semantic_tests must be non-empty"
    assert entry.provider_chain.primary in ALLOWED_PRIMARY_PROVIDERS, (
        f"{code}: provider_chain.primary={entry.provider_chain.primary!r} "
        f"not in the allowed set {ALLOWED_PRIMARY_PROVIDERS}"
    )


def test_corr_chart_grammar_is_heatmap() -> None:
    """CORR is the exemplar — rebuild rejects row-index plots for correlation."""
    entry = REGISTRY.get("CORR")
    assert entry.chart_grammar is not None, "CORR must declare a chart grammar"
    assert entry.chart_grammar.kind == ChartKind.HEATMAP, (
        f"CORR.chart_grammar.kind must be heatmap, got {entry.chart_grammar.kind!r}"
    )


def test_port_opt_chart_grammar_is_frontier() -> None:
    """PORT_OPT must render an efficient frontier, not a generic line chart."""
    entry = REGISTRY.get("PORT_OPT")
    assert entry.chart_grammar is not None, "PORT_OPT must declare a chart grammar"
    assert entry.chart_grammar.kind == ChartKind.FRONTIER, (
        f"PORT_OPT.chart_grammar.kind must be frontier, got {entry.chart_grammar.kind!r}"
    )


def test_blak_has_model_assumption_input() -> None:
    """BL hides nothing — priors, views, and tau ride model_assumption controls."""
    entry = REGISTRY.get("BLAK")
    assumption_inputs = [i for i in entry.inputs if i.control == ControlKind.MODEL_ASSUMPTION]
    assert assumption_inputs, (
        "BLAK must expose at least one model_assumption input (priors/views/tau)"
    )
