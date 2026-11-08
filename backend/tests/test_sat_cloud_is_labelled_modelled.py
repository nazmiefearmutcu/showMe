"""SAT#4: the cloud value is an Open-Meteo model value, and the payload says so.

The number comes from Open-Meteo's daily cloud_cover_mean at the AOI centroid,
not from the satellite image. Before the fix the row claimed the NASA GIBS source
and the field dictionary called it plain cloud cover. All network calls are patched.
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.misc import sat as sat_mod


def _run_with_patched_providers(monkeypatch):
    async def _tile(bbox, layer_id, requested):  # noqa: ARG001
        return {
            "state": "imagery",
            "capture_date": requested,
            "tile_url": "https://gibs.earthdata.nasa.gov/wms/tile.png",
            "checks": [],
            "reason": "",
        }

    monkeypatch.setattr(sat_mod, "_resolve_tile_candidates", _tile)
    handler = sat_mod.SATFunction()

    async def _conditions(lat, lon, date):  # noqa: ARG001
        return {"daily_cloud_mean_pct": 60.0, "current_cloud_pct": 40, "source": "open_meteo"}, 60.0

    handler._fetch_conditions = _conditions  # type: ignore[method-assign]
    return asyncio.run(handler.execute(aoi="cushing_ok", layer="true_color", capture_date="2026-11-01"))


def test_cloud_row_is_attributed_to_open_meteo_model_not_gibs(monkeypatch) -> None:
    result = _run_with_patched_providers(monkeypatch)
    row = result.data["rows"][0]
    assert row["cloud_pct"] == 60.0
    assert row["cloud_source"] == "open_meteo_model"
    assert "Open-Meteo" in row["cloud_label"]
    assert "modelled" in row["cloud_label"].lower()
    assert "gibs" not in row["cloud_label"].lower()


def test_cloud_field_dictionary_says_modelled_not_observed(monkeypatch) -> None:
    result = _run_with_patched_providers(monkeypatch)
    desc = result.data["field_dictionary"]["cloud_pct"].lower()
    assert "modelled" in desc
    assert "not read from the satellite image" in desc
    assert "proxy" in desc


def test_cloud_source_is_none_when_no_cloud_value(monkeypatch) -> None:
    async def _tile(bbox, layer_id, requested):  # noqa: ARG001
        return {
            "state": "imagery",
            "capture_date": requested,
            "tile_url": "https://gibs.earthdata.nasa.gov/wms/tile.png",
            "checks": [],
            "reason": "",
        }

    monkeypatch.setattr(sat_mod, "_resolve_tile_candidates", _tile)
    handler = sat_mod.SATFunction()

    async def _no_conditions(lat, lon, date):  # noqa: ARG001
        raise RuntimeError("offline test")

    handler._fetch_conditions = _no_conditions  # type: ignore[method-assign]
    result = asyncio.run(handler.execute(aoi="cushing_ok", layer="true_color", capture_date="2026-11-01"))
    row = result.data["rows"][0]
    assert row["cloud_pct"] is None
    assert row["cloud_source"] is None
    assert row["cloud_label"] is None
