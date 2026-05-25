"""Wave 1 macro + rates manifest seeds: ECO, ECST, WIRP, BTMM.

Covers registration, schema-shape sanity, and the spec-mandated special
assertions:
  * WIRP must declare a probs_sum_to_one semantic test (cut+hold+hike = 1)
  * ECO must promise an ``events`` field in its output contract
  * ECST must lead the provider chain with ``fred``
"""
from __future__ import annotations

import pytest

from showme.manifest import REGISTRY, load_seeds


_WAVE1_MACRO_CODES = ("ECO", "ECST", "WIRP", "BTMM")


@pytest.fixture(scope="module", autouse=True)
def _load_all_seeds() -> None:
    load_seeds()


@pytest.mark.parametrize("code", _WAVE1_MACRO_CODES)
def test_wave1_macro_seed_registered(code: str) -> None:
    """Each of ECO/ECST/WIRP/BTMM is in the registry after load_seeds()."""
    assert code in REGISTRY, f"manifest {code!r} not registered"
    entry = REGISTRY.get(code)
    assert entry.code == code, f"registered code {entry.code!r} != {code!r}"


@pytest.mark.parametrize("code", _WAVE1_MACRO_CODES)
def test_wave1_macro_seed_shape_is_sane(code: str) -> None:
    """Inputs non-empty, methodology ≥ 50 chars, semantic_tests non-empty."""
    entry = REGISTRY.get(code)
    assert entry.inputs, f"{code} must declare at least one input"
    assert len(entry.methodology) >= 50, (
        f"{code} methodology must be substantial (≥50 chars), "
        f"got {len(entry.methodology)}"
    )
    assert entry.semantic_tests, f"{code} must declare at least one semantic test"


def test_wirp_probs_sum_to_one_test_declared() -> None:
    """WIRP's contract MUST pin the cut+hold+hike = 1.0 invariant via a named test."""
    wirp = REGISTRY.get("WIRP")
    test_names = [t.name for t in wirp.semantic_tests]
    assert any("probs_sum_to_one" in name for name in test_names), (
        "WIRP must declare a semantic_test whose name contains "
        f"'probs_sum_to_one'; got {test_names!r}"
    )


def test_eco_output_contract_must_have_events() -> None:
    """ECO's deliverable is the events array; the output_contract must say so."""
    eco = REGISTRY.get("ECO")
    assert "events" in eco.output_contract.must_have, (
        "ECO output_contract.must_have must include 'events'; "
        f"got {eco.output_contract.must_have!r}"
    )


def test_ecst_primary_provider_is_fred() -> None:
    """ECST is the FRED series explorer — primary provider must be fred."""
    ecst = REGISTRY.get("ECST")
    assert ecst.provider_chain.primary == "fred", (
        "ECST primary provider must be 'fred'; "
        f"got {ecst.provider_chain.primary!r}"
    )
