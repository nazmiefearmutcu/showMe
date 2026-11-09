"""P2A-G06 SAT: unknown aoi / layer are explicit input errors, never silent substitutions.

Was: an unknown aoi silently became cushing_ok (Cushing OK tank farm) and an
unknown layer silently became true_color. That is a default location and a
default layer for a request that named neither, which the data policy forbids.

All tests run offline: the HTTP helper is stubbed to fail, so nothing is fetched.
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.misc import sat as sat_handler


def _run(coro):
    return asyncio.run(coro)


def _offline(monkeypatch) -> None:
    async def _no_network(url, params=None):
        raise RuntimeError("offline test")

    monkeypatch.setattr(sat_handler, "_http_get_raw", _no_network)


def test_sat_unknown_aoi_is_input_error(monkeypatch) -> None:
    _offline(monkeypatch)
    result = _run(sat_handler.SATFunction().execute(aoi="does_not_exist", layer="true_color"))
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []
    assert "does_not_exist" in result.data["reason"]
    assert "cushing_ok" not in str(result.data.get("aoi_label", ""))


def test_sat_unknown_layer_is_input_error(monkeypatch) -> None:
    _offline(monkeypatch)
    result = _run(sat_handler.SATFunction().execute(aoi="cushing_ok", layer="bogus"))
    assert result.data["status"] == "input_error"
    assert result.data["rows"] == []
    assert "bogus" in result.data["reason"]


def test_sat_custom_bbox_does_not_need_a_preset_aoi(monkeypatch) -> None:
    """A valid bbox replaces the preset, so an unknown preset name is not an error."""
    _offline(monkeypatch)
    result = _run(sat_handler.SATFunction().execute(
        aoi="does_not_exist", bbox="-122.55,37.70,-122.30,37.85", layer="true_color",
    ))
    assert result.data["status"] != "input_error"
    assert result.data["aoi_label"] == "custom bbox"


def test_sat_known_aoi_and_layer_are_not_input_errors(monkeypatch) -> None:
    _offline(monkeypatch)
    result = _run(sat_handler.SATFunction().execute(aoi="rotterdam_port", layer="ndvi"))
    assert result.data["status"] != "input_error"
    assert result.data["aoi"] == "rotterdam_port"
    assert result.data["layer"] == "ndvi"
