"""Cross-cutting regression tests for wb1-g07 (XCON-5 FRD text and inputs, XCON-9 backtest).

Network-free: a spot is supplied as an input, so the FRD handler never fetches
market data. The tests exercise the real FRDFunction.execute path, not only the
_forward helper, so a seed input that the handler ignores fails here.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace



def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _frd_fn():
    from showme.engine.functions.fx._funcs import FRDFunction

    fn = FRDFunction()
    fn.deps = SimpleNamespace()
    return fn


# --------------------------------------------------------------------------- #
# XCON-5 — FRD seed inputs, card slots and methodology must match the handler.
# --------------------------------------------------------------------------- #
def test_frd_seed_defines_r_quote_as_quote_currency_rate():
    from showme.manifest.seeds.frd_seed import frd

    text = frd.methodology
    # The computed forward puts the quote-currency rate in the numerator
    # (quote-per-base pricing), so the methodology must define r_quote as the quote rate.
    assert "r_quote is the quote-currency" in text
    assert "r_base is the base-currency" in text
    assert "r_dom" not in text
    assert "r_for" not in text


def test_frd_seed_rate_inputs_are_the_names_the_handler_reads():
    from showme.manifest.seeds.frd_seed import frd

    names = {spec.name for spec in frd.inputs}
    assert {"r_quote", "r_base", "spot"} <= names
    assert "r_dom" not in names and "r_for" not in names
    assert "spot_override" not in names


def test_frd_seed_has_no_placeholder_rate_defaults():
    """Rates the user does not enter must come from the handler's labelled
    reference rates, not from seed defaults that could contradict them."""
    from showme.manifest.seeds.frd_seed import frd

    assert "r_quote" not in frd.defaults
    assert "r_base" not in frd.defaults


def test_frd_card_slots_have_producers_in_handler_output():
    from showme.manifest.seeds.frd_seed import frd

    slot_keys = {slot.key for slot in frd.card_schema.slots}
    assert {"r_quote", "r_base"} <= slot_keys
    res = _run(_frd_fn().execute(pair="EURUSD", spot=1.08, r_quote=0.035, r_base=0.045))
    assert "r_quote" in res.data and "r_base" in res.data


def test_frd_handler_honours_seed_rate_inputs():
    """User-entered rates must reach the forward. Before the fix the handler read
    r_base/r_quote while the seed declared r_dom/r_for, so entered rates were ignored."""
    from showme.engine.functions.fx._funcs import _forward

    spot, r_quote, r_base = 1.08, 0.035, 0.045
    res = _run(_frd_fn().execute(pair="EURUSD", spot=spot, r_quote=r_quote, r_base=r_base))
    assert res.data["r_quote"] == r_quote
    assert res.data["r_base"] == r_base
    # The 3M row (index 2 of the default tenors) must equal the seed formula
    # F = S (1 + r_quote T') / (1 + r_base T'), T' = T x 365/360 (ACT/360).
    row_3m = res.data["rows"][2]
    assert row_3m["tenor"] == "3M"
    expected = _forward(spot, r_base=r_base, r_quote=r_quote, years=row_3m["tenor_years"])
    assert abs(row_3m["forward"] - round(expected, 6)) < 1e-9
    t_rate = row_3m["tenor_years"] * 365.0 / 360.0
    stated = spot * (1 + r_quote * t_rate) / (1 + r_base * t_rate)
    assert abs(row_3m["forward"] - round(stated, 6)) < 1e-6


def test_frd_seed_semantic_cip_test_uses_declared_inputs():
    from showme.manifest.seeds.frd_seed import frd

    names = {spec.name for spec in frd.inputs}
    cip = next(t for t in frd.semantic_tests if t.name == "frd_eurusd_3m_matches_cip_within_tolerance")
    assert set(cip.inputs) <= names
    assert {"r_quote", "r_base", "spot"} <= set(cip.inputs)


def test_frd_seed_day_count_matches_code():
    from showme.manifest.seeds.frd_seed import frd

    text = frd.methodology
    assert "ACT/360" in text
    assert "actual/365 simple interest" not in text


def test_frd_seed_formula_definitions_match_computed_direction():
    """With r_quote (USD) above r_base (EUR) the EURUSD forward must sit above spot,
    exactly as the seed's definitions imply."""
    from showme.engine.functions.fx._funcs import _forward

    spot = 1.10
    years = 0.25
    # r_quote = USD 5%, r_base = EUR 2%  ->  F > S.
    assert _forward(spot, r_base=0.02, r_quote=0.05, years=years) > spot
    # Swapped: r_quote = USD 2%, r_base = EUR 5%  ->  F < S.
    assert _forward(spot, r_base=0.05, r_quote=0.02, years=years) < spot
