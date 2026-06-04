"""De-garbage test for SAT (satellite / alt-data).

SAT used to be key-gated on Sentinel Hub: with no SENTINELHUB_CLIENT_ID /
SECRET it returned provider_unavailable and a synthetic SVG "bbox preview".
The fixed handler returns REAL keyless data:

  * a live NASA GIBS WMS tile URL for the AOI + layer + capture date
  * a real Open-Meteo conditions summary (cloud_pct proxy) for the AOI centroid

These tests assert the real-data contract and stay green offline: if the
network is unavailable the handler degrades to a clearly-labelled
provider_unavailable shape, which we accept.
"""

from __future__ import annotations

import asyncio

import pytest

from showme.engine.functions.misc.sat import SATFunction, _gibs_wms_url, _parse_bbox


def _run(coro):
    return asyncio.run(coro)


def _make_handler() -> SATFunction:
    # Construct via the registry/base contract used by sibling tests; SATFunction
    # only needs self.deps for optional adapters, which this handler no longer
    # depends on, so a bare instance is sufficient for the keyless path.
    try:
        return SATFunction()
    except TypeError:
        # Some BaseFunction variants require deps; pass a permissive stub.
        class _Deps:  # pragma: no cover - shape varies by codebase version
            def __getattr__(self, _name):
                return None

        return SATFunction(_Deps())  # type: ignore[call-arg]


OK_SET = {"ok", "partial", "provider_unavailable"}


def test_sat_tile_url_is_real_gibs_url():
    url = _gibs_wms_url((-96.91, 35.83, -96.62, 36.13), "MODIS_Terra_CorrectedReflectance_TrueColor", "2026-05-20")
    assert url.startswith("https://gibs.earthdata.nasa.gov/")
    assert "REQUEST=GetMap" in url
    assert "MODIS_Terra_CorrectedReflectance_TrueColor" in url
    assert "TIME=2026-05-20" in url
    # bbox is encoded as minLat,minLon,maxLat,maxLon for WMS 1.3.0 EPSG:4326
    assert "BBOX=35.830000,-96.910000,36.130000,-96.620000" in url


def test_parse_bbox_round_trip():
    assert _parse_bbox("-122.55,37.70,-122.30,37.85") == (-122.55, 37.70, -122.30, 37.85)
    assert _parse_bbox("bad") is None
    assert _parse_bbox(None) is None


def test_sat_returns_real_data_or_graceful_unavailable():
    handler = _make_handler()
    result = _run(handler.execute(aoi="cushing_ok", layer="true_color"))
    data = result.data

    assert data["status"] in OK_SET
    assert "methodology" in data and isinstance(data["methodology"], str) and data["methodology"]
    assert "field_dictionary" in data and isinstance(data["field_dictionary"], dict)
    assert result.code == "SAT"

    # No more Sentinel-Hub credential gating / synthetic SVG preview in the happy path.
    assert "Configure SENTINELHUB_CLIENT_ID" not in data.get("reason", "")
    assert "showme_bbox_preview" not in result.sources

    if data["status"] in {"ok", "partial"}:
        # Real keyless source must be cited.
        assert "nasa_gibs" in result.sources
        rows = data.get("rows") or []
        assert rows, "ok/partial must carry at least one row"
        row = rows[0]
        # tile_url must be a real, fetchable GIBS URL (not a placeholder/data: URL).
        assert isinstance(row["tile_url"], str)
        assert row["tile_url"].startswith("https://gibs.earthdata.nasa.gov/")
        assert "REQUEST=GetMap" in row["tile_url"]
        # cloud_pct should be numeric when Open-Meteo answered (it may be None only
        # if that single sub-provider was down, which is acceptable degradation).
        if data["status"] == "ok" and row.get("cloud_pct") is not None:
            assert isinstance(row.get("cloud_pct"), (int, float))
        # AOI/layer echoed honestly.
        assert data["aoi"] == "cushing_ok"
        assert data["layer"] == "true_color"
        # Conditions card present.
        cards = data.get("cards") or []
        assert cards and "aoi" in cards[0]
    else:
        # Genuine outage path: explicit, no fabrication.
        assert data.get("data_mode") == "not_configured"
        assert data.get("rows") == []
        assert data.get("reason")
        assert result.metadata.get("fallback") is True


def test_sat_lowest_cloud_unknown_aoi_falls_back():
    handler = _make_handler()
    result = _run(handler.execute(aoi="does_not_exist", layer="bogus"))
    data = result.data
    assert data["status"] in OK_SET
    if data["status"] in {"ok", "partial"}:
        # Unknown AOI/layer normalised to defaults, never crashes.
        assert data["aoi"] == "cushing_ok"
        assert data["layer"] == "true_color"


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-q"])
