"""DPF seed truth (P2a-g05, DPF#4).

The DPF manifest seed must describe the registered handler (dark pool / ATS
volume from FINRA), not a delisted-firms reference function.
"""
from __future__ import annotations

from showme.engine.functions.equity.dpf import DPFFunction
from showme.manifest import REGISTRY, load_seeds


def _seed():
    load_seeds()
    return REGISTRY.get("DPF")


def test_dpf_seed_name_matches_handler() -> None:
    assert _seed().name == DPFFunction.name == "Dark Pool / ATS Volume"


def test_dpf_seed_does_not_describe_delisted_firms() -> None:
    seed = _seed()
    blob = " ".join([seed.name, seed.intent, seed.methodology]).lower()
    assert "delist" not in blob
    assert "form 25" not in blob
    assert "private firm" not in blob


def test_dpf_seed_primary_provider_is_finra() -> None:
    assert _seed().provider_chain.primary == "finra"


def test_dpf_seed_percent_field_is_documented_as_percent() -> None:
    seed = _seed()
    assert "percent" in seed.field_dict["dark_pool_pct"].description.lower()
    assert "0-100" in seed.field_dict["dark_pool_pct"].description
