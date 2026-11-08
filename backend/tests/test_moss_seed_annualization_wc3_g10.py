"""WC3-G10 MOSS#2: the seed text states the annualization the handler really uses.

The handler annualizes crypto daily vol with sqrt(365) and exchange assets with
sqrt(252) (WC1-G19). The seed's methodology and intent still said sqrt(252) for
everything, which is the help text an operator reads.
"""
from __future__ import annotations

from showme.engine.functions.misc._bonus import _MOSS_CRYPTO_PERIODS, _MOSS_EXCHANGE_PERIODS
from showme.manifest import REGISTRY, load_seeds


def _moss():
    load_seeds()
    return REGISTRY.get("MOSS")


def test_moss_seed_methodology_names_the_crypto_factor() -> None:
    """Pre-fix: the seed methodology said 'sqrt(252)' for all assets, crypto included."""
    entry = _moss()
    assert _MOSS_CRYPTO_PERIODS == 365 and _MOSS_EXCHANGE_PERIODS == 252
    assert "sqrt(365)" in entry.methodology, entry.methodology
    assert "crypto" in entry.methodology.lower()


def test_moss_seed_intent_does_not_claim_one_factor_for_every_asset() -> None:
    """Pre-fix: the intent read 'std of daily close-to-close returns × sqrt(252)' with no crypto caveat."""
    entry = _moss()
    assert "sqrt(365)" in entry.intent, entry.intent
