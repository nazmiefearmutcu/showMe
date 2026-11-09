"""CPF#1 — every series id the CPF manifest offers must have its own futures
proxy in CPF_SERIES_MAP, and every series that is not mapped must be an
explicit input error. The older degarbage test pins a hard-coded tuple, so a
manifest option added without a map entry (the way PNGASEUUSDM was exposed)
would pass unnoticed; this test reads the option list from the manifest itself.
"""
from __future__ import annotations

from showme.engine.functions.commodity._funcs import CPF_SERIES_MAP
from showme.manifest import REGISTRY, load_seeds


def _manifest_series_options() -> list[str]:
    load_seeds(module_names=["cpf_seed"])
    entry = REGISTRY.get("CPF")
    series_input = next(i for i in entry.inputs if i.name == "series_id")
    return list(series_input.options or [])


def test_every_manifest_series_option_has_its_own_futures_proxy() -> None:
    options = _manifest_series_options()
    assert options, "the CPF manifest must declare series options"
    missing = [opt for opt in options if opt not in CPF_SERIES_MAP]
    assert missing == [], f"manifest offers series without a price source: {missing}"
    for opt in options:
        entry = CPF_SERIES_MAP[opt]
        assert entry["futures"].endswith("=F"), opt
        assert entry["unit"], opt


def test_no_manifest_option_is_routed_to_another_instrument_name() -> None:
    # A mapped series must carry the label of the instrument it actually trades.
    # The European gas id must never reach a Henry Hub contract.
    options = _manifest_series_options()
    assert "PNGASEUUSDM" not in options
    if "DHHNGSP" in CPF_SERIES_MAP:
        assert "Henry Hub" in CPF_SERIES_MAP["DHHNGSP"]["name"]
