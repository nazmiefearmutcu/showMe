"""DINE — Nominatim place-search contract (density, bounds, honesty).

Pins the improved DINE lookup:

* the requested limit is clamped to Nominatim's documented maximum (40);
* the location is geocoded once and the place search is BOUNDED to that
  viewbox (so "New York restaurant" searches inside NYC, not the planet);
* amenity keywords use the ``[keyword]`` special-phrase form inside a
  bounded viewbox;
* rows carry the fields OSM actually has (compact address, type/category,
  cuisine, opening hours, distance from the area centre) with rating/price
  left None — nothing fabricated;
* duplicate OSM objects are deduped;
* repeat calls within the cache TTL do not re-hit the provider.

Every test fakes the HTTP layer (``_nominatim_get``) so the suite is
offline and fast; the real throttle/User-Agent policy is pinned in
``test_session_04_bughunt.py``.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from showme.engine.functions.misc import _extras


def _run(coro):
    return asyncio.run(coro)


def _bbox_payload() -> list[dict[str, Any]]:
    return [{
        "lat": "40.7127281",
        "lon": "-74.0060152",
        "display_name": "New York, United States",
        "boundingbox": ["40.4765780", "40.9176300", "-74.2588430", "-73.7002330"],
    }]


def _place(
    name: str,
    osm_id: int,
    *,
    ptype: str = "restaurant",
    hours: str | None = "Mo-Su 11:00-23:00",
    cuisine: str | None = "italian",
) -> dict[str, Any]:
    return {
        "name": name,
        "display_name": f"{name}, 123 Test Street, Manhattan, New York, 10001, United States",
        "lat": "40.7200000",
        "lon": "-74.0000000",
        "osm_type": "node",
        "osm_id": osm_id,
        "place_id": 5000 + osm_id,
        "category": "amenity",
        "type": ptype,
        "address": {
            "house_number": "123",
            "road": "Test Street",
            "suburb": "Manhattan",
            "city": "New York",
            "postcode": "10001",
        },
        "extratags": {
            "opening_hours": hours,
            "cuisine": cuisine,
        },
    }


class _FakeNominatim:
    """Records call params and serves canned payloads per query."""

    def __init__(self, search_payload: list[dict[str, Any]]):
        self.search_payload = search_payload
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, params: dict[str, Any]) -> list[dict[str, Any]]:
        self.calls.append(dict(params))
        if params.get("q") == "New York":
            return _bbox_payload()
        return self.search_payload

    @property
    def search_calls(self) -> list[dict[str, Any]]:
        return [call for call in self.calls if call.get("q") != "New York"]


@pytest.fixture(autouse=True)
def _clear_dine_cache() -> None:
    _extras._nominatim_cache.clear()


def _install(monkeypatch: pytest.MonkeyPatch, payload: list[dict[str, Any]]) -> _FakeNominatim:
    fake = _FakeNominatim(payload)
    monkeypatch.setattr(_extras, "_nominatim_get", fake)
    return fake


def test_limit_is_clamped_to_provider_maximum(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, [_place("Bistro A", 1)])
    rows = _run(_extras._nominatim_restaurants("restaurant", "New York", 50))
    assert rows, "fake payload must produce rows"
    search = fake.search_calls[-1]
    # Nominatim's documented maximum is 40 — never ask for more.
    assert search["limit"] == _extras._NOMINATIM_MAX_LIMIT == 40


def test_search_is_bounded_to_location_viewbox(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, [_place("Bistro A", 1)])
    _run(_extras._nominatim_restaurants("restaurant", "New York", 25))
    search = fake.search_calls[-1]
    assert search["bounded"] == 1
    assert search["viewbox"] == "-74.258843,40.476578,-73.700233,40.91763"
    # The amenity special phrase is what turns "restaurant" into every
    # tagged restaurant inside the box instead of name matches.
    assert search["q"] == "[restaurant]"


def test_non_amenity_keyword_keeps_text_query_inside_viewbox(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake = _install(monkeypatch, [_place("Sushi Seki", 2)])
    _run(_extras._nominatim_restaurants("sushi", "New York", 25))
    search = fake.search_calls[-1]
    assert search["q"] == "sushi"
    assert search["bounded"] == 1


def test_rows_parse_osm_fields_and_compute_distance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch, [_place("Bistro A", 1)])
    rows = _run(_extras._nominatim_restaurants("restaurant", "New York", 25))
    assert len(rows) == 1
    row = rows[0]
    assert row["name"] == "Bistro A"
    assert row["address"] == "123 Test Street, Manhattan, New York, 10001"
    assert row["type"] == "restaurant"
    assert row["category"] == "amenity"
    assert row["cuisine"] == "italian"
    assert row["opening_hours"] == "Mo-Su 11:00-23:00"
    assert row["osm_id"] == 1 and row["place_id"] == 5001
    # Distance is measured from the bounded area's centre (city centre),
    # so it is a finite, non-negative number.
    assert isinstance(row["distance_km"], float)
    assert row["distance_km"] >= 0
    # Ratings/prices are never fabricated.
    assert row["rating"] is None and row["price"] is None
    assert row["source_mode"] == "openstreetmap_nominatim"


def test_duplicate_osm_objects_are_deduped(monkeypatch: pytest.MonkeyPatch) -> None:
    duplicate = _place("Bistro A", 7)
    _install(monkeypatch, [duplicate, dict(duplicate), _place("Bistro B", 8)])
    rows = _run(_extras._nominatim_restaurants("restaurant", "New York", 25))
    assert [row["name"] for row in rows] == ["Bistro A", "Bistro B"]


def test_results_are_cached_within_ttl(monkeypatch: pytest.MonkeyPatch) -> None:
    fake = _install(monkeypatch, [_place("Bistro A", 1)])
    first = _run(_extras._nominatim_restaurants("restaurant", "New York", 25))
    calls_after_first = len(fake.calls)
    second = _run(_extras._nominatim_restaurants("restaurant", "New York", 25))
    assert second == first
    # Cached: no new Nominatim request (neither geocode nor search).
    assert len(fake.calls) == calls_after_first


def test_no_bbox_falls_back_to_free_text_search(monkeypatch: pytest.MonkeyPatch) -> None:
    async def _no_geo(params: dict[str, Any]) -> list[dict[str, Any]]:
        if params.get("q") == "Nowhere":
            return []
        return [_place("Bistro A", 1)]

    monkeypatch.setattr(_extras, "_nominatim_get", _no_geo)
    rows = _run(_extras._nominatim_restaurants("restaurant", "Nowhere", 25))
    assert rows and rows[0]["name"] == "Bistro A"
