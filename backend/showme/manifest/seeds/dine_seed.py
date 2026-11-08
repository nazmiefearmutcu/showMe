"""DINE — Restaurant lookup (non-core).

DINE is an auxiliary off-topic utility that searches OpenStreetMap
Nominatim for food places near a location. It is not a finance function
and carries low nav weight: it belongs in the miscellaneous tray, not the
finance-first workspace default.
"""
from __future__ import annotations

from ..enums import (
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    CardSchema,
    CardSlot,
    ColumnSpec,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def dine() -> FunctionManifest:
    return FunctionManifest(
        code="DINE",
        name="Restaurants",
        category=Category.MISC,
        intent=(
            "Food places near a location from OpenStreetMap, an auxiliary off-topic "
            "utility for the cockpit's miscellaneous tray, not a finance function."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="location",
                label="Location",
                control=ControlKind.TEXT,
                required=False,
                description="Place name geocoded with OpenStreetMap Nominatim. Required: DINE does not guess a city.",
            ),
            InputSpec(
                name="query",
                label="Search",
                control=ControlKind.TEXT,
                required=False,
                description="Amenity keyword such as restaurant, cafe or sushi (default restaurant).",
            ),
            InputSpec(
                name="cuisine",
                label="Cuisine",
                control=ControlKind.SELECT,
                required=False,
                description=(
                    "Keep only places whose OSM cuisine tag (or OSM type) matches. Applied to the "
                    "places Nominatim returns for the search, so it can narrow the list to zero."
                ),
                options=["any", "turkish", "italian", "japanese", "mexican", "indian", "cafe"],
            ),
        ],
        defaults={
            "query": "restaurant",
            "cuisine": "any",
        },
        provider_chain=ProviderChain(
            primary="openstreetmap_nominatim",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=False,
            next_actions=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="cuisine", label="Cuisine", kind="tag"),
                ColumnSpec(key="type", label="OSM type", kind="tag"),
                ColumnSpec(key="address", label="Address", kind="text"),
                ColumnSpec(key="distance_km", label="Distance (km)", kind="number", format="%.2f"),
                ColumnSpec(key="rating", label="Rating", kind="number", format="%.1f"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="entry_count", label="Places", kind="kpi"),
                CardSlot(key="top_pick", label="Top pick", kind="badge"),
            ],
        ),
        methodology=(
            "DINE is an auxiliary utility, low nav weight in the finance-first workspace. "
            "It lives in the miscellaneous tray. The location is geocoded with OpenStreetMap "
            "Nominatim (a city-level match is preferred over a state match), then the place "
            "search is bounded to that area. Rows are OSM places with their OSM address, type "
            "and cuisine tags; distance_km is the great-circle distance from the geocoded point "
            "of the location match. Ratings and prices are not available from OSM and are never "
            "fabricated: the rating field stays empty. When Nominatim is unreachable the result "
            "is status provider_unavailable with a reason, never placeholder rows."
        ),
        field_dict={
            "rows[].name": FieldDef(description="Place name from OpenStreetMap.", source="openstreetmap_nominatim"),
            "rows[].address": FieldDef(description="Compact street address from OSM address tags.", source="openstreetmap_nominatim"),
            "rows[].cuisine": FieldDef(description="OSM cuisine tag when the mapper supplied one.", source="openstreetmap_nominatim"),
            "rows[].type": FieldDef(description="OSM place type (e.g. restaurant, cafe, fast_food).", source="openstreetmap_nominatim"),
            "rows[].distance_km": FieldDef(description="Great-circle distance from the geocoded location point, km (not a route).", source="computed"),
            "rows[].rating": FieldDef(description="Always empty: OSM carries no ratings.", source="openstreetmap_nominatim"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="dine_provider_unavailable_returns_explicit_state_not_rows",
                description="When Nominatim is unavailable DINE returns status provider_unavailable with rows=[] and a reason, never synthetic restaurants.",
                inputs={"location": "New York"},
                assertions=["status_is_provider_unavailable_when_nominatim_fails", "rows_is_empty_array_when_unavailable"],
            ),
            SemanticTest(
                name="dine_filter_cuisine_excludes_others",
                description="With cuisine='italian' every returned row has cuisine or type matching 'italian'.",
                inputs={"cuisine": "italian"},
                assertions=["every_row_cuisine_or_type_equals_italian"],
            ),
        ],
    )


__all__ = ["dine"]
