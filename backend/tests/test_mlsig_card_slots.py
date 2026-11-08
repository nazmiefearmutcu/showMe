"""MLSIG card slots must read keys the function really emits (MLSIG seed, card_schema).

A card slot whose key no output produces renders an empty KPI. Those slots are
removed or pointed at the measured field they describe, never filled with a
constant.
"""

from __future__ import annotations

from showme.engine.functions.portfolio.mlsig import _no_measured_result
from showme.manifest.seeds.mlsig_seed import mlsig


def _emitted_keys() -> set[str]:
    data = _no_measured_result(
        "AAPL", "EQUITY", 365, 1, status="needs_input", reason="probe", next_actions=["x"]
    )
    return set(data) | set(data["summary"])


def test_every_mlsig_card_slot_has_an_emitted_key() -> None:
    emitted = _emitted_keys()
    missing = [slot.key for slot in mlsig.card_schema.slots if slot.key not in emitted]

    assert missing == []


def test_mlsig_card_slots_drop_invented_confidence_and_paper_mode() -> None:
    keys = {slot.key for slot in mlsig.card_schema.slots}

    assert "latest_confidence" not in keys
    assert "paper_mode" not in keys
    assert "oos_score" not in keys
