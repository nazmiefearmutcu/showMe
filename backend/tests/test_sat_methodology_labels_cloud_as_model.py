"""SAT#4 wording: the methodology must not call the Open-Meteo cloud value 'real'.

The cloud percentage is Open-Meteo's modelled daily mean at the AOI centroid. The
methodology string is part of the payload, so it must say the same thing the
field dictionary and row label say. All network calls are patched.
"""
from __future__ import annotations

import asyncio

from showme.engine.functions.misc import sat as sat_mod


def _methodology(monkeypatch) -> str:
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
    result = asyncio.run(handler.execute(aoi="cushing_ok", layer="true_color", capture_date="2026-11-01"))
    return str(result.data["methodology"])


def test_methodology_does_not_call_open_meteo_cloud_a_real_value(monkeypatch) -> None:
    text = _methodology(monkeypatch).lower()
    assert "real value reported by open-meteo" not in text
    assert "modelled" in text
    assert "not read from the satellite image" in text
