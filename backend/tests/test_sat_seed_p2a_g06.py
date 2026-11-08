"""P2A-G06 SAT#6: the SAT manifest must describe the keyless NASA GIBS handler.

The handler (engine/functions/misc/sat.py) serves NASA GIBS MODIS/VIIRS tiles
plus Open-Meteo conditions with no credential. The seed used to describe a
Sentinel-2 / SentinelHub / Planet credential-gated pane. These tests pin the
seed to the handler's real inputs, sources and output keys.
"""
from __future__ import annotations

import asyncio
import re

from showme.engine.functions.misc import sat as sat_handler
from showme.manifest.seeds.sat_seed import sat


def _all_text(manifest) -> str:
    parts = [manifest.intent, manifest.methodology]
    parts += [t.name + " " + t.description for t in manifest.semantic_tests]
    parts += [i.description or "" for i in manifest.inputs]
    parts += [fd.description for fd in manifest.field_dict.values()]
    return " ".join(parts)


def test_sat_seed_does_not_describe_sentinel_or_credentials() -> None:
    text = _all_text(sat).lower()
    for banned in ("sentinelhub", "sentinel hub", "sentinel-2", "planet", "client_id", "keyring", "credential"):
        assert banned not in text, f"seed still mentions {banned!r}"


def test_sat_seed_names_the_keyless_gibs_and_open_meteo_sources() -> None:
    text = (sat.intent + " " + sat.methodology).lower()
    assert "nasa gibs" in text
    assert "open-meteo" in text
    assert "keyless" in text or "no api key" in text or "no key" in text


def test_sat_seed_aoi_and_layer_options_match_handler_presets() -> None:
    aoi = next(i for i in sat.inputs if i.name == "aoi")
    layer = next(i for i in sat.inputs if i.name == "layer")
    assert set(aoi.options) == set(sat_handler._AOI_PRESETS)
    assert set(layer.options) == set(sat_handler._GIBS_LAYERS)
    assert sat.defaults["aoi"] in aoi.options
    assert sat.defaults["layer"] in layer.options


def test_sat_seed_fields_match_handler_row_and_card_keys() -> None:
    row_keys = {"capture_utc", "aoi", "layer", "cloud_pct", "tile_url", "source"}
    columns = {c.key for c in sat.table_schema.columns}
    assert columns == row_keys
    card_keys = {s.key for s in sat.card_schema.slots}
    assert {"aoi", "latest_capture", "cloud_pct", "data_mode", "as_of"} <= card_keys


def test_sat_seed_cloud_cover_is_labelled_as_open_meteo_proxy() -> None:
    desc = sat.field_dict["rows[].cloud_pct"].description.lower()
    assert "open-meteo" in desc
    assert "proxy" in desc


def test_sat_seed_semantic_tests_match_handler_behaviour() -> None:
    names = {t.name for t in sat.semantic_tests}
    assert any("unavailable" in n for n in names)
    assert all("sentinel" not in n.lower() for n in names)
    for t in sat.semantic_tests:
        assert "lowest" not in t.name and "lowest_cloud" not in " ".join(t.assertions), (
            "handler reads one capture day; it does not pick the lowest-cloud capture"
        )


def test_sat_handler_output_satisfies_seed_must_have() -> None:
    from showme.engine.functions.misc.sat import SATFunction

    # Force the outage branch offline: both providers unreachable.
    async def _down(*_a, **_k):
        raise RuntimeError("offline test")

    handler = SATFunction()
    handler._fetch_conditions = _down  # type: ignore[method-assign]
    handler._probe_tile = _down  # type: ignore[method-assign]
    result = asyncio.run(handler.execute(aoi="cushing_ok", layer="true_color"))
    for key in sat.output_contract.must_have:
        assert key in result.data, f"must_have {key} missing"
    assert result.data["data_mode"] == "not_configured"
    assert result.data["rows"] == []
