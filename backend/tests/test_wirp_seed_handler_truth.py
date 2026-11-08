"""WIRP manifest seed must describe the inputs and method the handler really ships.

The pane and the handler use ``central_bank`` and ``meetings``. The seed used to
declare ``central_banks``, ``meeting_horizon``, ``source``, ``as_of`` and
``provider_mode``, which the handler never reads (a dead ``source`` control),
and described a SOFR/OIS implied-path method, a 'modeled' fallback, a terminal
rate and per-bank implied_path rows that do not exist.
"""
from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, load_seeds

_HANDLER_PARAMS = {"central_bank", "meetings"}
_UNIMPLEMENTED_MARKERS = (
    "implied_path",
    "terminal",
    "modeled",
    "sofr",
    "monotonic",
    "central_banks",
    "meeting_horizon",
    "banks[]",
    "banks_",
)


@pytest.fixture(scope="module", autouse=True)
def _seeds() -> None:
    load_seeds()


def _semantic_blob(entry) -> str:
    return " ".join(
        f"{t.name} {t.description} {' '.join(t.assertions)}" for t in entry.semantic_tests
    ).lower()


def test_wirp_declared_inputs_are_exactly_the_handler_params() -> None:
    entry = REGISTRY.get("WIRP")
    declared = {spec.name for spec in entry.inputs}
    assert declared == _HANDLER_PARAMS, declared


def test_wirp_defaults_match_handler_defaults() -> None:
    entry = REGISTRY.get("WIRP")
    assert entry.defaults.get("central_bank") == "FED"
    assert entry.defaults.get("meetings") == 4


def test_wirp_methodology_does_not_claim_unimplemented_method() -> None:
    entry = REGISTRY.get("WIRP")
    text = (entry.methodology + " " + _semantic_blob(entry)).lower()
    for marker in _UNIMPLEMENTED_MARKERS:
        assert marker not in text, f"seed still describes unimplemented {marker!r}"
    assert "fedwatch" in entry.methodology.lower()
    assert "provider_unavailable" in entry.methodology


def test_wirp_field_dict_only_names_emitted_fields() -> None:
    entry = REGISTRY.get("WIRP")
    keys = " ".join(entry.field_dict.keys()).lower()
    for marker in ("implied_path", "banks[]", "terminal"):
        assert marker not in keys, keys
    assert "rows[].implied_change_bp" in entry.field_dict
    assert "rows[].cut_25bp" in entry.field_dict
