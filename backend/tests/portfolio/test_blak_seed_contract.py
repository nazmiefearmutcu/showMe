"""BLAK#5 follow-up: the manifest and the agent usage describe the inputs the engine reads.

The seed used to declare ``risk_aversion`` (the engine reads ``delta``) and no
``views_text`` input (the pane sends it). The agent usage text had dropped the
market-cap override. These tests pin the aligned contract.
"""

from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, ControlKind, load_seeds
from showme.server_routes._agent_runtime import _function_usage


@pytest.fixture(scope="module", autouse=True)
def _load() -> None:
    load_seeds()


def _input(name: str):
    entry = REGISTRY.get("BLAK")
    matches = [i for i in entry.inputs if i.name == name]
    return matches[0] if matches else None


def test_seed_declares_delta_not_risk_aversion() -> None:
    assert _input("delta") is not None
    assert _input("risk_aversion") is None
    entry = REGISTRY.get("BLAK")
    assert entry.defaults.get("delta") == 2.5
    assert "risk_aversion" not in entry.defaults


def test_seed_declares_the_pane_text_inputs() -> None:
    views_text = _input("views_text")
    assert views_text is not None
    assert views_text.required is False
    assert "LONG>SHORT" in views_text.description
    market_caps = _input("market_caps")
    assert market_caps is not None
    # Overrides are optional: without them the provider cap is used and the
    # equal-weight fallback is labelled. "Required" was a false statement.
    assert market_caps.required is False
    assert "SYMBOL:USD" in market_caps.description


def test_seed_card_slot_points_at_a_real_output_key() -> None:
    entry = REGISTRY.get("BLAK")
    keys = {slot.key for slot in entry.card_schema.slots}
    assert "risk_aversion" not in keys
    assert "delta" in keys


def test_seed_still_has_model_assumption_controls() -> None:
    assumption = [i for i in REGISTRY.get("BLAK").inputs if i.control == ControlKind.MODEL_ASSUMPTION]
    assert assumption


def test_agent_usage_names_the_market_cap_override_and_text_views() -> None:
    usage = _function_usage("BLAK", "Black-Litterman", "portfolio", "", ["equity"])
    text = " ".join(usage["steps"]) + " " + " ".join(usage["inputs"])
    assert "market_caps" in usage["inputs"] or "Market caps" in text
    assert "views_text" in usage["inputs"]
    assert "SYMBOL:USD" in text
    assert "LONG>SHORT" in text
