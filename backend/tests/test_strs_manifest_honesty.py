"""STRS#4 — every STRS manifest input and claim must match what the engine runs (p1a-g05).

The engine applies hand-set parametric shocks; the only measured inputs are the
bond-fund window returns in GFC_2008 and COVID_2020. The manifest must not claim
historical replay, a factor model, or a propagation method the engine ignores.
"""

from __future__ import annotations

from showme.manifest import REGISTRY, load_seeds


def _strs():
    load_seeds()
    return REGISTRY.get("STRS")


def _input(strs, name):
    return next(i for i in strs.inputs if i.name == name)


def test_intent_does_not_claim_replay_or_factor_shocks():
    intent = _strs().intent.lower()
    assert "replay" not in intent, intent
    assert "factor-shock" not in intent and "factor shock" not in intent, intent
    assert "hand-set" in intent, intent


def test_scenario_magnitudes_does_not_claim_historical_replay():
    desc = _input(_strs(), "scenario_magnitudes").description.lower()
    assert "historical replay" not in desc, desc
    assert "hand-set" in desc or "base calibration" in desc, desc


def test_propagation_offers_only_the_method_the_engine_runs():
    prop = _input(_strs(), "propagation")
    assert "factor_model" not in (prop.options or []), prop.options
    assert "historical_replay" not in (prop.options or []), prop.options
    assert "factor model" not in prop.description.lower(), prop.description
    assert "replay" not in prop.description.lower(), prop.description


def test_propagation_default_is_an_offered_option():
    strs = _strs()
    prop = _input(strs, "propagation")
    default = (strs.defaults or {}).get("propagation")
    assert default in (prop.options or []), (default, prop.options)
    assert default != "historical_replay"


def test_methodology_names_the_measured_exception_and_its_fallback():
    method = _strs().methodology.lower()
    assert "measured" in method, method
    assert "unavailable" in method, method
    assert "bond" in method, method
