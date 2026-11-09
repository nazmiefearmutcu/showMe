"""P2A-G12 review follow-up: EREV label must not claim EPS estimate revisions.

Offline: no provider is contacted.
"""
from __future__ import annotations


def _manifest(code: str):
    from showme.manifest.registry import REGISTRY
    from showme.manifest.seeds import load_seeds

    load_seeds()
    return REGISTRY.get(code)


# ─────────────────────────────────────────────────────────────────────────
# EREV#1 — the function label must not claim EPS estimate revisions
# ─────────────────────────────────────────────────────────────────────────


def test_erev_label_does_not_claim_earnings_revisions() -> None:
    from showme.engine.functions.equity.erev import EREVFunction

    label = "Analyst Recommendation Momentum"
    assert EREVFunction.name == label
    assert _manifest("EREV").name == label
