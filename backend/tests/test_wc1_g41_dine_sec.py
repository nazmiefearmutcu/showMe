"""wc1-g41: DINE honesty fixes (DINE#1-#4).

Offline: every HTTP call is faked (``_nominatim_get`` for DINE, an httpx
MockTransport for Stooq).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from showme.engine.core.base_function import FunctionDeps
from showme.engine.functions.misc import _extras
from showme.manifest.seeds.dine_seed import dine

_DINE_SEED_PATH = Path(__file__).resolve().parents[1] / "showme" / "manifest" / "seeds" / "dine_seed.py"
_EXTRAS_PATH = Path(__file__).resolve().parents[1] / "showme" / "engine" / "functions" / "misc" / "_extras.py"

NYC_POINT = ("40.7127281", "-74.0060152")
NYC_BBOX = ["40.4765780", "40.9176300", "-74.2588430", "-73.7002330"]
STATE_BBOX = ["40.4765780", "45.0158611", "-79.7619758", "-71.7909720"]


def _run(coro: Any) -> Any:
    return asyncio.run(coro)


def _geo_city_first() -> list[dict[str, Any]]:
    """Nominatim order for q='New York': the state comes first, the city second."""
    return [
        {
            "lat": "43.1561681", "lon": "-75.8449946",
            "display_name": "New York, United States",
            "addresstype": "state",
            "boundingbox": STATE_BBOX,
        },
        {
            "lat": NYC_POINT[0], "lon": NYC_POINT[1],
            "display_name": "New York, United States",
            "addresstype": "city",
            "boundingbox": NYC_BBOX,
        },
    ]


def _place(name: str, osm_id: int, *, cuisine: str | None, ptype: str = "restaurant",
           lat: str = "40.7200000", lon: str = "-74.0000000") -> dict[str, Any]:
    return {
        "name": name,
        "display_name": f"{name}, Test Street, New York",
        "lat": lat,
        "lon": lon,
        "osm_type": "node",
        "osm_id": osm_id,
        "place_id": 9000 + osm_id,
        "category": "amenity",
        "type": ptype,
        "address": {"road": "Test Street", "city": "New York"},
        "extratags": {"cuisine": cuisine},
    }


class _FakeNominatim:
    def __init__(self, places: list[dict[str, Any]], geo: list[dict[str, Any]] | None = None):
        self.places = places
        self.geo = geo if geo is not None else _geo_city_first()
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append(dict(params))
        if params.get("format") == "jsonv2" and "addressdetails" not in params:
            return self.geo
        return self.places


@pytest.fixture(autouse=True)
def _clear_dine_cache() -> None:
    _extras._nominatim_cache.clear()


def _install(monkeypatch: pytest.MonkeyPatch, fake: _FakeNominatim) -> _FakeNominatim:
    monkeypatch.setattr(_extras, "_nominatim_get", fake)
    return fake


def _execute(**params: Any) -> Any:
    return _run(_extras.DINEFunction(FunctionDeps()).execute(**params))


# ── DINE#1: declared cuisine input must filter ─────────────────────────


def test_cuisine_filter_keeps_only_matching_places(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeNominatim([
        _place("Lokanta", 1, cuisine="turkish"),
        _place("Trattoria", 2, cuisine="italian"),
        _place("Meze House", 3, cuisine="turkish;mediterranean"),
        _place("Unlabelled", 4, cuisine=None),
    ]))
    result = _execute(location="New York", cuisine="turkish")
    names = [row["name"] for row in result.data["rows"]]
    assert names == ["Lokanta", "Meze House"]
    assert result.data["status"] == "live"
    assert result.data["cuisine_filter"]["matched"] == 2


def test_cuisine_filter_with_no_match_is_explicit_empty_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeNominatim([_place("Trattoria", 2, cuisine="italian")]))
    result = _execute(location="New York", cuisine="japanese")
    assert result.data["status"] == "empty"
    assert result.data["rows"] == []
    assert "japanese" in result.data["reason"]


def test_cuisine_any_does_not_filter(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeNominatim([
        _place("Lokanta", 1, cuisine="turkish"),
        _place("Trattoria", 2, cuisine="italian"),
    ]))
    result = _execute(location="New York", cuisine="any")
    assert len(result.data["rows"]) == 2
    assert result.data["cuisine_filter"] is None


def test_seed_declares_only_inputs_the_handler_honours() -> None:
    manifest = dine
    names = {spec.name for spec in manifest.inputs}
    assert "price_band" not in names, "OSM has no price data; the input must not be declared"
    assert names <= {"location", "query", "cuisine"}
    assert "price_band" not in {col.key for col in manifest.table_schema.columns}


# ── DINE#2: provider, docstring and seed describe the live contract ─────


def test_seed_describes_openstreetmap_not_yelp_or_no_provider() -> None:
    manifest = dine
    assert manifest.provider_chain.primary == "openstreetmap_nominatim"
    text = (manifest.methodology + " " + manifest.intent).lower()
    assert "openstreetmap" in text
    assert "yelp" not in text
    assert "no external provider" not in text
    source = _DINE_SEED_PATH.read_text(encoding="utf-8")
    assert "Yelp" not in source


def test_dine_docstring_names_the_real_provider() -> None:
    doc = _extras.DINEFunction.__doc__ or ""
    assert "Yelp" not in doc
    assert "OpenStreetMap" in doc


def test_no_location_is_needs_input_not_another_city(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _FakeNominatim([_place("Lokanta", 1, cuisine="turkish")]))
    result = _execute()
    assert result.data["status"] == "needs_input"
    assert result.data["rows"] == []
    assert fake.calls == [], "no provider call may happen without a location"


# ── DINE#3: distance origin is the geocoded point, not the bbox midpoint ─


def test_distance_is_measured_from_geocoded_point(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeNominatim([_place("Bistro A", 1, cuisine="italian",
                                                 lat="40.7200000", lon="-74.0000000")]))
    rows = _run(_extras._nominatim_restaurants("restaurant", "New York", 25))
    expected = _extras._haversine(float(NYC_POINT[0]), float(NYC_POINT[1]), 40.72, -74.0)
    midpoint = _extras._haversine(
        (40.4765780 + 40.9176300) / 2, (-74.2588430 + -73.7002330) / 2, 40.72, -74.0
    )
    assert rows[0]["distance_km"] == pytest.approx(expected, abs=0.01)
    assert abs(rows[0]["distance_km"] - midpoint) > 0.5, "must not be the bbox midpoint"


# ── DINE#4: city-level geocode match beats the state match ──────────────


def test_geocode_prefers_city_match_over_state(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeNominatim([]))
    geo = _run(_extras._nominatim_viewbox("New York"))
    assert geo["geocoded_addresstype"] == "city"
    assert geo["center"] == (float(NYC_POINT[0]), float(NYC_POINT[1]))
    assert geo["viewbox"] == "-74.258843,40.476578,-73.700233,40.91763"


def test_geocode_requests_several_candidates(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, _FakeNominatim([]))
    _run(_extras._nominatim_viewbox("New York"))
    assert fake.calls[0]["limit"] > 1


def test_result_reports_which_place_was_geocoded(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch, _FakeNominatim([_place("Bistro A", 1, cuisine="italian")]))
    result = _execute(location="New York")
    assert result.data["location_match"]["addresstype"] == "city"
    assert result.data["location_match"]["display_name"] == "New York, United States"
