"""Smoke tests for the wave-1 market-data manifest seeds.

Asserts every code in {GP, HP, DES, FA, WATCH, TOP, CN, QUOTE} is
registered with the contract floors the rebuild relies on: non-empty
inputs, a known provider, a non-empty methodology, and at least one
semantic test. Anything below the floor breaks the manifest pipeline
that drives backend handlers, frontend controls, and docs.
"""
from __future__ import annotations

import pytest

from showme.manifest.registry import REGISTRY
from showme.manifest.seeds import load_seeds


WAVE1_CODES = ("GP", "HP", "DES", "FA", "WATCH", "TOP", "CN", "QUOTE")

# Provider names registered in showme.providers + the alias chain names
# the manifests legitimately reference (cached_snapshot, rss, etc.).
KNOWN_PRIMARY_PROVIDERS = frozenset(
    {
        "sec_edgar",
        "fred",
        "treasury_direct",
        "openfigi",
        "binance",
        "yfinance",
        "gdelt",
        "rss",
    }
)


@pytest.fixture(scope="module", autouse=True)
def _load_seeds_once() -> None:
    """Populate REGISTRY before any wave-1 test runs."""
    load_seeds()


def test_every_wave1_code_is_registered() -> None:
    codes = set(REGISTRY.codes())
    missing = [c for c in WAVE1_CODES if c not in codes]
    assert not missing, f"wave-1 manifest seeds not registered: {missing}"


@pytest.mark.parametrize("code", WAVE1_CODES)
def test_wave1_manifest_meets_floor(code: str) -> None:
    entry = REGISTRY.get(code)

    assert entry.code == code, f"{code}: manifest.code mismatch ({entry.code!r})"
    assert entry.inputs, f"{code}: inputs must be non-empty"

    primary = entry.provider_chain.primary
    assert primary in KNOWN_PRIMARY_PROVIDERS, (
        f"{code}: provider_chain.primary={primary!r} is not in the known set"
    )

    assert entry.semantic_tests, f"{code}: semantic_tests must be non-empty"

    methodology = entry.methodology or ""
    assert len(methodology) >= 50, (
        f"{code}: methodology must be at least 50 chars (got {len(methodology)})"
    )
