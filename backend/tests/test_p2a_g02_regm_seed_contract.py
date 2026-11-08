"""REGM#3 — the published REGM contract must use the renamed input_coverage key.

The payload reports ``input_coverage`` (share of four components that resolved),
not a probability. The seed must not still require, index or define
``confidence``, and the 'Confidence floor' control must say it has no effect,
because no code reads ``model_threshold``.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from showme.engine.functions.macro.regm import REGMFunction  # noqa: E402
from showme.manifest.seeds.regm_seed import regm  # noqa: E402


def test_output_contract_requires_input_coverage_not_confidence() -> None:
    must_have = regm.output_contract.must_have
    assert "input_coverage" in must_have, must_have
    assert "confidence" not in must_have, must_have


def test_card_slots_use_the_emitted_input_coverage_key() -> None:
    slot_keys = {s.key for s in regm.card_schema.slots}
    assert "confidence" not in slot_keys, slot_keys
    assert "input_coverage" in slot_keys, slot_keys


def test_field_dict_defines_input_coverage_not_a_probability() -> None:
    assert "confidence" not in regm.field_dict, list(regm.field_dict)
    entry = regm.field_dict["input_coverage"]
    assert "not a probability" in entry.description.lower(), entry.description


def test_confidence_floor_states_it_is_not_wired() -> None:
    """No code reads model_threshold; the control must not claim it gates labels."""
    floor = next(i for i in regm.inputs if i.name == "model_threshold")
    text = floor.description.lower()
    assert "not wired" in text or "no effect" in text, floor.description
    assert "transitional" not in text, floor.description


def test_seed_does_not_claim_transitional_gating() -> None:
    assert "transitional" not in regm.methodology.lower(), regm.methodology
    assert all("transitional" not in t.name for t in regm.semantic_tests)


def test_seed_contract_keys_are_emitted_by_the_payload() -> None:
    """input_coverage (the renamed key) is really in the payload."""
    fn = REGMFunction()

    class _Boom:
        async def get(self, url, timeout=None):  # noqa: ANN001
            raise RuntimeError("network down")

    fn._http_client = _Boom()
    out = asyncio.run(fn.execute(symbol="SPY", allow_model=True))
    assert "input_coverage" in out.data
    assert "confidence" not in out.data
