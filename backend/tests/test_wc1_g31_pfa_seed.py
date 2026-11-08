"""WC1 g31 PFA#4 — the PFA manifest must describe the Brinson function the handler runs.

The seed used to describe a CAPM/FF factor regression (factor_model, window,
portfolio_source inputs) while pfa.py computes sector Brinson attribution from
four typed maps. The contract must match the handler.
"""
from __future__ import annotations

from showme.manifest import REGISTRY, load_seeds
from showme.engine.functions.portfolio.pfa import PFAFunction


def _entry():
    load_seeds()
    return REGISTRY.get("PFA")


def test_pfa_manifest_name_matches_handler_name() -> None:
    entry = _entry()
    # RED before fix: the seed said "Portfolio Factor Analysis".
    assert entry.name == PFAFunction.name


def test_pfa_manifest_inputs_are_the_brinson_maps() -> None:
    names = [i.name for i in _entry().inputs]
    # RED before fix: the seed declared factor_model / window / portfolio_source instead.
    assert names == ["port_weights", "port_returns", "bench_weights", "bench_returns"]
    for forbidden in ("factor_model", "window", "portfolio_source", "risk_free_rate"):
        assert forbidden not in names


def test_pfa_manifest_methodology_is_brinson_not_factor_regression() -> None:
    text = _entry().methodology.lower()
    assert "brinson" in text and "allocation" in text and "selection" in text
    assert "ken french" not in text and "factor regression" not in text and "hac" not in text
