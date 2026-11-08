"""FRH#1: the FRH manifest must describe what the handler actually returns.

The handler reads only ``symbols`` and ``limit``, returns one funding snapshot
per symbol (fraction per funding interval, not annualised), and has no window,
bucket, quote-currency, matrix or open-interest ranking. The manifest must not
promise those.
"""
from __future__ import annotations

from showme.manifest.seeds.frh_seed import frh

HANDLER_INPUTS = {"symbols", "limit", "provider_mode"}


def test_inputs_are_only_ones_the_handler_reads():
    names = {spec.name for spec in frh.inputs}
    assert names <= HANDLER_INPUTS, names - HANDLER_INPUTS


def test_no_annualisation_formula_or_open_interest_ranking_claims():
    text = (frh.methodology + " " + frh.intent).lower()
    # "not annualised" is a correct disclaimer; the old formula and ranking claims are not.
    assert "annualized_rate" not in text and "3 * 365" not in text and "1095" not in text
    assert "open_interest" not in text and "open interest" not in text
    assert "8h window" not in text


def test_unit_is_fraction_per_funding_interval():
    assert "fraction per funding interval" in frh.methodology.lower()
    assert frh.field_dict["rows[].avg"].unit == "fraction_per_interval"


def test_output_contract_does_not_promise_matrix_or_buckets():
    assert "matrix" not in frh.output_contract.must_have
    assert "buckets" not in frh.output_contract.must_have


def test_provider_chain_matches_handler_venues():
    assert frh.provider_chain.primary == "binance"
    assert set(frh.provider_chain.fallbacks) == {"bybit", "okx"}
    assert "cached_snapshot" not in frh.provider_chain.fallbacks
