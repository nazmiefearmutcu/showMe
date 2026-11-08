"""Cross-cutting regression tests for wb1-g07 (XCON-5 FRD text, XCON-9 backtest).

Network-free: these assert the documented formula and annualisation contract
against the computed values, without fetching any market data.
"""
from __future__ import annotations


# --------------------------------------------------------------------------- #
# XCON-5 — FRD methodology must describe the formula the code computes.
# --------------------------------------------------------------------------- #
def test_frd_seed_defines_r_dom_as_quote_currency_rate():
    from showme.manifest.seeds.frd_seed import frd

    text = frd.methodology
    # The computed forward puts the quote-currency rate in the numerator
    # (quote-per-base pricing), so r_dom must be defined as the QUOTE rate.
    assert "r_dom is the quote-currency" in text
    assert "r_for is the base-currency" in text
    assert "r_dom is the base-currency" not in text


def test_frd_seed_day_count_matches_code():
    from showme.manifest.seeds.frd_seed import frd

    text = frd.methodology
    assert "ACT/360" in text
    assert "actual/365 simple interest" not in text


def test_frd_seed_formula_definitions_match_computed_direction():
    """With r_dom (quote/USD) above r_for (base/EUR) the EURUSD forward must
    sit above spot, exactly as the seed's definitions imply."""
    from showme.engine.functions.fx._funcs import _forward

    spot = 1.10
    years = 0.25
    # r_dom = USD (quote) 5%, r_for = EUR (base) 2%  ->  F > S.
    assert _forward(spot, r_base=0.02, r_quote=0.05, years=years) > spot
    # Swapped: r_dom = USD 2%, r_for = EUR 5%  ->  F < S.
    assert _forward(spot, r_base=0.05, r_quote=0.02, years=years) < spot


def test_frd_seed_cip_example_matches_act360_convention():
    """The seed's stated formula, evaluated with its own T' = T x 365/360, must
    reproduce the function's forward to 1e-9."""
    from showme.engine.functions.fx._funcs import _forward

    spot, r_dom, r_for, years = 1.08, 0.035, 0.045, 0.25
    t_rate = years * 365.0 / 360.0
    stated = spot * (1 + r_dom * t_rate) / (1 + r_for * t_rate)
    # Seed convention: r_dom = quote, r_for = base -> _forward(S, r_base=r_for, r_quote=r_dom, T)
    assert abs(_forward(spot, r_base=r_for, r_quote=r_dom, years=years) - stated) < 1e-9

