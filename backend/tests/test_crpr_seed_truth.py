"""CRPR manifest seed must describe the SEC-derived model the handler ships.

The handler no longer ships a bundled three-agency public profile
(``manual_or_public_defaults``). A corporate issuer gets one ``model_implied``
row from SEC companyfacts, a sovereign gets an empty payload, and only a pinned
``rating`` override echoes three agency rows.
"""
from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, load_seeds


@pytest.fixture(scope="module", autouse=True)
def _seeds() -> None:
    load_seeds()


def _entry():
    return REGISTRY.get("CRPR")


def _semantic_blob(entry) -> str:
    return " ".join(
        f"{t.name} {t.description} {' '.join(t.assertions)}" for t in entry.semantic_tests
    ).lower()


def test_crpr_methodology_does_not_describe_bundled_public_profile() -> None:
    entry = _entry()
    text = (entry.methodology + " " + entry.intent).lower()
    assert "manual_or_public_defaults" not in text
    assert "public/default" not in text
    assert "bundled" not in text
    assert "model" in entry.methodology.lower()
    assert "sec" in entry.methodology.lower()


def test_crpr_semantic_tests_do_not_expect_three_rows_for_a_corporate_issuer() -> None:
    entry = _entry()
    blob = _semantic_blob(entry)
    assert "crpr_emits_three_agency_rows" not in blob
    assert "manual_or_public_defaults" not in blob
    assert "crpr_default_response_is_labelled" not in blob


def test_crpr_semantic_tests_describe_single_model_implied_row() -> None:
    blob = _semantic_blob(_entry())
    assert "model_implied" in blob
    assert "rows_length_equals_1" in blob


def test_crpr_override_three_rows_test_pins_a_rating_input() -> None:
    entry = _entry()
    three_row = [t for t in entry.semantic_tests if "rows_length_equals_3" in t.assertions]
    assert three_row, "override path still emits three agency rows and must say so"
    assert all("rating" in t.inputs for t in three_row), [t.inputs for t in three_row]
