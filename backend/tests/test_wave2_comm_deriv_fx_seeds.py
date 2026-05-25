"""Wave 2 commodities / derivatives / FX manifest seeds.

Covers the 13 codes in this batch:

  COMMODITIES: BGAS, BOIL, CPF, GLCO, NGAS, WETR
  DERIVATIVES: OSA, OVME
  FX:          FRD, FXFC, FXH, FXIP, WCRS

Asserts every code registers, the shared shape floor (non-empty
inputs / methodology ≥ 50 chars / at least one semantic test), the
correct ``Category`` per code, and the per-code spec exemplars:

  * WCRS  → chart_grammar.kind == HEATMAP (NOT row-index)
  * OSA / OVME → chart_grammar.kind == PAYOFF
  * GLCO  → chart_grammar.kind == BAR_LADDER
  * CPF   → chart_grammar.kind == TIME_SERIES_LINE, primary == fred
  * BGAS / BOIL / NGAS → futures unit + expiry_month in output_contract
  * WETR  → declares the ``explicit_provider_unavailable_when_no_weather_key`` semantic test
  * FRD   → formula_dict contains the CIP formula
  * FXIP  → mirrors GP grammar (TIME_SERIES_CANDLES)
"""
from __future__ import annotations

import pytest

from showme.manifest import (
    REGISTRY,
    Category,
    ChartKind,
    load_seeds,
)


WAVE2_SEED_MODULES = (
    "bgas_seed",
    "boil_seed",
    "cpf_seed",
    "frd_seed",
    "fxfc_seed",
    "fxh_seed",
    "fxip_seed",
    "glco_seed",
    "ngas_seed",
    "osa_seed",
    "ovme_seed",
    "wcrs_seed",
    "wetr_seed",
)

WAVE2_CODES = (
    "BGAS",
    "BOIL",
    "CPF",
    "FRD",
    "FXFC",
    "FXH",
    "FXIP",
    "GLCO",
    "NGAS",
    "OSA",
    "OVME",
    "WCRS",
    "WETR",
)

EXPECTED_CATEGORY = {
    "BGAS": Category.COMMODITIES,
    "BOIL": Category.COMMODITIES,
    "CPF": Category.COMMODITIES,
    "GLCO": Category.COMMODITIES,
    "NGAS": Category.COMMODITIES,
    "WETR": Category.COMMODITIES,
    "OSA": Category.DERIVATIVES,
    "OVME": Category.DERIVATIVES,
    "FRD": Category.FX,
    "FXFC": Category.FX,
    "FXH": Category.FX,
    "FXIP": Category.FX,
    "WCRS": Category.FX,
}


@pytest.fixture(scope="module", autouse=True)
def _load_wave2_seeds() -> None:
    """Import only the 13 wave-2 seeds. We do NOT call ``load_seeds()`` with
    no args because other agents' in-flight seeds in this directory may
    have unrelated import errors that would mask wave-2 regressions.
    """
    load_seeds(module_names=WAVE2_SEED_MODULES)


# ---------------------------------------------------------------------------
# Registration + shape floor
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", WAVE2_CODES)
def test_wave2_seed_is_registered(code: str) -> None:
    assert code in REGISTRY, f"{code} seed must be registered by load_seeds()"


@pytest.mark.parametrize("code", WAVE2_CODES)
def test_wave2_seed_shape(code: str) -> None:
    """Every wave-2 seed shares the same minimum-quality bar."""
    entry = REGISTRY.get(code)
    assert entry.code == code, f"{code}: registered code mismatch"
    assert entry.inputs, f"{code}: must declare at least one input"
    assert len(entry.methodology) >= 50, (
        f"{code}: methodology must be substantial (≥50 chars), "
        f"got {len(entry.methodology)}"
    )
    assert entry.semantic_tests, f"{code}: must declare at least one semantic test"


@pytest.mark.parametrize("code", WAVE2_CODES)
def test_wave2_seed_category(code: str) -> None:
    """Each code lands in the expected Category bucket."""
    entry = REGISTRY.get(code)
    assert entry.category is EXPECTED_CATEGORY[code], (
        f"{code}: category={entry.category} expected {EXPECTED_CATEGORY[code]}"
    )


# ---------------------------------------------------------------------------
# WCRS — must be HEATMAP, not row-index
# ---------------------------------------------------------------------------


def test_wcrs_chart_grammar_is_heatmap() -> None:
    """WCRS user-visible exemplar is the cross-rate heatmap (per spec)."""
    wcrs = REGISTRY.get("WCRS")
    assert wcrs.chart_grammar is not None, "WCRS must declare a chart_grammar"
    assert wcrs.chart_grammar.kind == ChartKind.HEATMAP, (
        "WCRS must render as a HEATMAP (NOT a row-index plot); got "
        f"{wcrs.chart_grammar.kind}"
    )


def test_wcrs_declares_heatmap_semantic_test() -> None:
    """WCRS must pin the heatmap-grammar invariant via a named semantic test."""
    wcrs = REGISTRY.get("WCRS")
    test_names = [t.name for t in wcrs.semantic_tests]
    assert "wcrs_chart_grammar_is_heatmap" in test_names, (
        "WCRS must declare a semantic_test named "
        f"'wcrs_chart_grammar_is_heatmap'; got {test_names!r}"
    )


# ---------------------------------------------------------------------------
# OSA / OVME — must render payoff diagrams
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ("OSA", "OVME"))
def test_option_pricer_chart_is_payoff(code: str) -> None:
    """OSA + OVME both render the payoff diagram at expiry."""
    entry = REGISTRY.get(code)
    assert entry.chart_grammar is not None, f"{code} must declare chart_grammar"
    assert entry.chart_grammar.kind == ChartKind.PAYOFF, (
        f"{code} must render as PAYOFF; got {entry.chart_grammar.kind}"
    )


def test_ovme_inputs_include_model_assumption_block() -> None:
    """OVME accepts underlying, strike, expiry, r, q, vol, and a model selector."""
    ovme = REGISTRY.get("OVME")
    input_names = {ip.name for ip in ovme.inputs}
    must_have = {"underlying", "strike", "expiry", "model", "risk_free", "dividend_yield", "volatility"}
    missing = must_have - input_names
    assert not missing, f"OVME missing inputs: {missing}"


def test_osa_inputs_include_leg_list_and_model() -> None:
    """OSA's first-class input is the multi-leg list plus a model assumption."""
    osa = REGISTRY.get("OSA")
    input_names = {ip.name for ip in osa.inputs}
    must_have = {"underlying", "legs", "model", "risk_free", "dividend_yield"}
    missing = must_have - input_names
    assert not missing, f"OSA missing inputs: {missing}"


# ---------------------------------------------------------------------------
# GLCO — bar ladder
# ---------------------------------------------------------------------------


def test_glco_chart_is_bar_ladder_or_none() -> None:
    """GLCO is a global-mover board; render as bar_ladder per spec."""
    glco = REGISTRY.get("GLCO")
    # Spec allows ``bar_ladder`` or ``none`` (table) — assert what we shipped.
    assert glco.chart_grammar is not None, "GLCO must declare a chart_grammar"
    assert glco.chart_grammar.kind == ChartKind.BAR_LADDER, (
        f"GLCO must render as BAR_LADDER; got {glco.chart_grammar.kind}"
    )


# ---------------------------------------------------------------------------
# CPF — FRED-backed forecast time-series
# ---------------------------------------------------------------------------


def test_cpf_chart_is_time_series_line() -> None:
    """CPF plots actual + forecast as a time-series line."""
    cpf = REGISTRY.get("CPF")
    assert cpf.chart_grammar is not None
    assert cpf.chart_grammar.kind == ChartKind.TIME_SERIES_LINE, (
        f"CPF must render as TIME_SERIES_LINE; got {cpf.chart_grammar.kind}"
    )


def test_cpf_primary_provider_is_fred() -> None:
    """CPF is a FRED commodity forecast series — primary provider must be fred."""
    cpf = REGISTRY.get("CPF")
    assert cpf.provider_chain.primary == "fred", (
        f"CPF primary provider must be 'fred'; got {cpf.provider_chain.primary!r}"
    )


def test_cpf_must_have_forecast_vintage() -> None:
    """CPF must promise the forecast_vintage field so stale vintages cannot hide."""
    cpf = REGISTRY.get("CPF")
    assert "forecast_vintage" in cpf.output_contract.must_have, (
        "CPF output_contract.must_have must include 'forecast_vintage'; "
        f"got {cpf.output_contract.must_have!r}"
    )


# ---------------------------------------------------------------------------
# Futures benchmarks (BGAS / NGAS / BOIL) — unit + expiry contract
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("code", ("BGAS", "NGAS", "BOIL"))
def test_futures_benchmark_must_have_contract_unit_and_expiry(code: str) -> None:
    """BGAS/NGAS/BOIL must declare contract_unit + expiry_month in their must_have."""
    entry = REGISTRY.get(code)
    must = set(entry.output_contract.must_have)
    assert "contract_unit" in must, (
        f"{code} output_contract.must_have must include 'contract_unit'; got {sorted(must)!r}"
    )
    assert "expiry_month" in must, (
        f"{code} output_contract.must_have must include 'expiry_month'; got {sorted(must)!r}"
    )


@pytest.mark.parametrize("code", ("BGAS", "NGAS", "BOIL"))
def test_futures_benchmark_primary_is_yfinance(code: str) -> None:
    """Futures-style tickers (RB=F, NG=F, BZ=F) are served by yfinance."""
    entry = REGISTRY.get(code)
    assert entry.provider_chain.primary == "yfinance", (
        f"{code} primary provider must be 'yfinance'; got {entry.provider_chain.primary!r}"
    )


# ---------------------------------------------------------------------------
# WETR — labelled provider-unavailable path
# ---------------------------------------------------------------------------


def test_wetr_declares_explicit_provider_unavailable_test() -> None:
    """WETR's spec mandates a semantic_test for the no-weather-key path."""
    wetr = REGISTRY.get("WETR")
    test_names = [t.name for t in wetr.semantic_tests]
    assert "explicit_provider_unavailable_when_no_weather_key" in test_names, (
        "WETR must declare a semantic_test named "
        f"'explicit_provider_unavailable_when_no_weather_key'; got {test_names!r}"
    )


# ---------------------------------------------------------------------------
# FRD — CIP formula must be visible in the formula_dict
# ---------------------------------------------------------------------------


def test_frd_formula_dict_includes_cip() -> None:
    """FRD declares the covered_interest_parity formula explicitly."""
    frd = REGISTRY.get("FRD")
    assert frd.formula_dict, "FRD must declare formulas in formula_dict"
    assert "covered_interest_parity" in frd.formula_dict, (
        "FRD.formula_dict must contain 'covered_interest_parity'; got "
        f"{sorted(frd.formula_dict.keys())!r}"
    )


# ---------------------------------------------------------------------------
# FXIP — mirrors GP grammar (candles)
# ---------------------------------------------------------------------------


def test_fxip_chart_is_time_series_candles() -> None:
    """FXIP is the FX-side GP — same TIME_SERIES_CANDLES grammar."""
    fxip = REGISTRY.get("FXIP")
    assert fxip.chart_grammar is not None
    assert fxip.chart_grammar.kind == ChartKind.TIME_SERIES_CANDLES, (
        f"FXIP must render as TIME_SERIES_CANDLES; got {fxip.chart_grammar.kind}"
    )


def test_fxip_must_have_base_and_quote_ccy() -> None:
    """FXIP exposes base + quote currency so users always see which side is which."""
    fxip = REGISTRY.get("FXIP")
    must = set(fxip.output_contract.must_have)
    assert "base_ccy" in must, f"FXIP must_have should include base_ccy; got {sorted(must)!r}"
    assert "quote_ccy" in must, f"FXIP must_have should include quote_ccy; got {sorted(must)!r}"


# ---------------------------------------------------------------------------
# FXH — hedge calculator inputs
# ---------------------------------------------------------------------------


def test_fxh_inputs_include_exposure_tenor_hedge_ratio_shock() -> None:
    """FXH per spec: inputs include exposure, tenor, hedge_ratio, shock."""
    fxh = REGISTRY.get("FXH")
    input_names = {ip.name for ip in fxh.inputs}
    must_have = {"exposure_notional", "tenor", "hedge_ratio", "spot_shock_pct"}
    missing = must_have - input_names
    assert not missing, f"FXH missing inputs per spec: {missing}"
