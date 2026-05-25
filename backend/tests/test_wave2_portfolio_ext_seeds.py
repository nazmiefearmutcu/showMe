"""Wave-2 contract tests for the extended portfolio + risk seed family.

Covers BMTX, BTFW, BTUNE, GREEKS, LOTS, MARS, MGN, MLSIG, PCAS, PFA,
PORT_WHATIF, PSC, PVAR, REBA, RPAR, STRS, TLH, TRA.

Pins:
  * Each code registers with a sane shape (inputs, methodology length,
    semantic_tests, Category.PORTFOLIO).
  * RPAR / PVAR / STRS each expose ≥ 1 model_assumption input — the
    rebuild contract refuses to ship risk surfaces with hidden defaults.
  * Research surfaces (RPAR, MARS, PSC, REBA, TLH, PORT_WHATIF, BMTX,
    BTFW, BTUNE, MLSIG) default paper_mode=True so weights/recs cannot
    fire live orders from the research pane.
  * TLH explicitly carries a wash-sale-respecting semantic test.
  * MGN explicitly pins that margin numbers come from broker, not
    client-side modeling.
"""
from __future__ import annotations

import pytest

from showme.manifest import Category, ControlKind, REGISTRY, load_seeds


WAVE2_PORTFOLIO_EXT_CODES = (
    "BMTX",
    "BTFW",
    "BTUNE",
    "GREEKS",
    "LOTS",
    "MARS",
    "MGN",
    "MLSIG",
    "PCAS",
    "PFA",
    "PORT_WHATIF",
    "PSC",
    "PVAR",
    "REBA",
    "RPAR",
    "STRS",
    "TLH",
    "TRA",
)

# Providers permitted as the primary in this family. `internal` covers
# the optimizer / what-if / VaR / stress family that lives in the
# handler layer; ccxt_broker is the placeholder for broker-backed
# flows (LOTS, MGN, GREEKS, TRA); yfinance is the public market-data
# fallback for PFA's factor pulls.
ALLOWED_PRIMARY_PROVIDERS = {
    "ccxt_broker",
    "yfinance",
    "binance",
    "fred",
    "internal",
}


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    load_seeds()


@pytest.mark.parametrize("code", WAVE2_PORTFOLIO_EXT_CODES)
def test_wave2_portfolio_ext_seed_registered(code: str) -> None:
    """Each code is registered after load_seeds() — no missing seed."""
    assert code in REGISTRY, f"manifest {code!r} not registered"
    entry = REGISTRY.get(code)
    assert entry.code == code, f"registered code {entry.code!r} != {code!r}"


@pytest.mark.parametrize("code", WAVE2_PORTFOLIO_EXT_CODES)
def test_wave2_portfolio_ext_seed_shape_is_sane(code: str) -> None:
    """Inputs non-empty, methodology substantial, at least one semantic test."""
    entry = REGISTRY.get(code)
    assert entry.inputs, f"{code}: inputs must be non-empty"
    assert len(entry.methodology) >= 50, (
        f"{code}: methodology must be ≥ 50 chars, got {len(entry.methodology)}"
    )
    assert entry.semantic_tests, f"{code}: semantic_tests must be non-empty"
    assert entry.category == Category.PORTFOLIO, (
        f"{code}: category must be PORTFOLIO, got {entry.category!r}"
    )
    assert entry.provider_chain.primary in ALLOWED_PRIMARY_PROVIDERS, (
        f"{code}: provider_chain.primary={entry.provider_chain.primary!r} "
        f"not in the allowed set {ALLOWED_PRIMARY_PROVIDERS}"
    )


# Risk surfaces whose model assumptions must be exposed (not hidden).
_MODEL_ASSUMPTION_REQUIRED = ("RPAR", "PVAR", "STRS")


@pytest.mark.parametrize("code", _MODEL_ASSUMPTION_REQUIRED)
def test_risk_surface_has_model_assumption_input(code: str) -> None:
    """RPAR/PVAR/STRS each expose ≥ 1 model_assumption input."""
    entry = REGISTRY.get(code)
    assumption_inputs = [
        i for i in entry.inputs if i.control == ControlKind.MODEL_ASSUMPTION
    ]
    assert assumption_inputs, (
        f"{code} must expose at least one model_assumption input "
        f"(risk_target / confidence / scenarios — never silent defaults)"
    )


# Research surfaces that default paper_mode=True.
_PAPER_SAFE_DEFAULTS = (
    "RPAR",
    "MARS",
    "PSC",
    "REBA",
    "TLH",
    "PORT_WHATIF",
    "BMTX",
    "BTFW",
    "BTUNE",
    "MLSIG",
)


@pytest.mark.parametrize("code", _PAPER_SAFE_DEFAULTS)
def test_research_surface_defaults_paper_mode_true(code: str) -> None:
    """Research surfaces default paper_mode=True so no live trade can fire."""
    entry = REGISTRY.get(code)
    assert "paper_mode" in entry.defaults, (
        f"{code} must declare paper_mode in defaults"
    )
    assert entry.defaults["paper_mode"] is True, (
        f"{code}.defaults['paper_mode'] must be True, "
        f"got {entry.defaults['paper_mode']!r}"
    )


def test_tlh_semantic_test_pins_wash_sale_rule() -> None:
    """TLH must carry a semantic test enforcing the wash-sale-rule contract."""
    tlh = REGISTRY.get("TLH")
    test_names = [t.name for t in tlh.semantic_tests]
    assert any("wash_sale" in name for name in test_names), (
        "TLH must declare a semantic_test whose name contains "
        f"'wash_sale'; got {test_names!r}"
    )


def test_mgn_semantic_test_pins_numbers_come_from_broker() -> None:
    """MGN must carry a semantic test asserting numbers come from broker, not modeled."""
    mgn = REGISTRY.get("MGN")
    test_names = [t.name for t in mgn.semantic_tests]
    assert any(
        "broker" in name and ("not_modeled" in name or "not modeled" in name)
        for name in test_names
    ), (
        "MGN must declare a semantic_test whose name asserts broker-sourced "
        f"(not client-side-modeled) margin numbers; got {test_names!r}"
    )


def test_rpar_methodology_mentions_parity_equation() -> None:
    """RPAR methodology must reference the parity equation (σ_i × w_i = c)."""
    rpar = REGISTRY.get("RPAR")
    text = rpar.methodology
    assert "parity" in text.lower(), (
        "RPAR methodology must mention 'parity'"
    )
    # The formula dict must carry the parity condition explicitly.
    assert "ParityCondition" in rpar.formula_dict, (
        "RPAR.formula_dict must include the ParityCondition formula"
    )


def test_pvar_options_cover_standard_confidence_levels() -> None:
    """PVAR confidence_level options must include 0.95, 0.99, 0.995."""
    pvar = REGISTRY.get("PVAR")
    conf_input = next(i for i in pvar.inputs if i.name == "confidence_level")
    assert conf_input.options is not None, "PVAR confidence_level must declare options"
    for required in (0.95, 0.99, 0.995):
        assert required in conf_input.options, (
            f"PVAR confidence_level options must include {required}; "
            f"got {conf_input.options!r}"
        )


def test_strs_scenarios_options_include_named_history() -> None:
    """STRS scenarios option list must include canonical historical windows."""
    strs = REGISTRY.get("STRS")
    scen_input = next(i for i in strs.inputs if i.name == "scenarios")
    assert scen_input.options is not None, "STRS scenarios must declare options"
    required_scenarios = {"lehman_2008", "covid_2020"}
    options_set = set(scen_input.options)
    missing = required_scenarios - options_set
    assert not missing, (
        f"STRS scenarios must include {required_scenarios}; missing {missing}"
    )
