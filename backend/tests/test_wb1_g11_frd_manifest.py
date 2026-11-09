"""FRD manifest (frd_seed.py) must describe the handler's real behaviour.

* FRD#2 — no stale numeric rate defaults are injected for r_dom / r_for; the
  rates must come from the live policy series or be explicitly supplied.
* FRD#3 — the documented CIP formula is F = S(1 + r_quote T)/(1 + r_base T)
  (S quote-per-base), matching the handler and the pane subtitle.
* FRD#4 — the documented day count is ACT/360 (the handler's convention), and
  forward_points is in price units with pips reported separately.
"""
from __future__ import annotations

from showme.manifest.seeds.frd_seed import frd as _frd_manifest


def _manifest():
    # The @manifest() decorator already yields the FunctionManifest object.
    return _frd_manifest


def test_no_stale_rate_defaults_for_domestic_or_foreign_rate() -> None:
    """FRD#2: r_dom / r_for must not inject the 2024-era 0.035 / 0.045 constants."""
    m = _manifest()
    assert "r_dom" not in m.defaults
    assert "r_for" not in m.defaults


def test_cip_formula_uses_quote_rate_in_numerator_and_base_rate_in_denominator() -> None:
    """FRD#3: F = S (1 + r_quote T) / (1 + r_base T) for a quote-per-base spot."""
    m = _manifest()
    expression = m.formula_dict["covered_interest_parity"].expression
    numerator, _, denominator = expression.partition(r"\frac{")[2].partition("}{")
    assert "r_{quote}" in numerator
    assert "r_{base}" in denominator
    assert "r_{dom}" not in expression and "r_{for}" not in expression


def test_methodology_states_the_corrected_cip_formula() -> None:
    m = _manifest()
    assert "F = S × (1 + r_quote × T) / (1 + r_base × T)" in m.methodology
    assert "F = S × (1 + r_dom × T) / (1 + r_for × T)" not in m.methodology


def test_methodology_states_act_360_day_count_not_act_365() -> None:
    """FRD#4: the handler applies ACT/360 to both legs."""
    m = _manifest()
    assert "ACT/360" in m.methodology
    assert "actual/365" not in m.methodology


def test_forward_points_unit_is_price_and_pips_are_separate() -> None:
    """FRD#4: the handler returns forward_points in price units; pips are their own field."""
    m = _manifest()
    assert m.field_dict["forward_points"].unit != "pips"
    assert m.field_dict["forward_points_pips"].unit == "pips"
