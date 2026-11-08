"""FLY — Flight tracking (OpenSky ADS-B state vectors, keyless).

FLY reads OpenSky ``/states/all`` through the ``opensky`` adapter and returns
aircraft state vectors. Route origin and destination are not inferred. When
OpenSky is unavailable, not configured, or returns no match, the handler says
so explicitly; it never shows sample aircraft.
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
def fly() -> FunctionManifest:
    return FunctionManifest(
        code="FLY",
        name="Flight Tracking",
        category=Category.MISC,
        intent=(
            "Live aircraft positions from the OpenSky ADS-B state-vector feed, "
            "filterable by callsign and origin country."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="callsign",
                label="Callsign",
                control=ControlKind.TEXT,
                required=False,
                description="Callsign substring filter (case-insensitive). Blank returns any callsign.",
            ),
            InputSpec(
                name="country",
                label="Country",
                control=ControlKind.TEXT,
                required=False,
                description="Origin-country substring filter (case-insensitive). Blank returns any country.",
            ),
            InputSpec(
                name="limit",
                label="Limit",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum aircraft rows returned (1 to 100).",
                min=1,
                max=100,
                step=1,
                unit="aircraft",
            ),
            InputSpec(
                name="reference",
                label="Reference only",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Skip the live OpenSky feed and return an explicit empty state.",
            ),
        ],
        defaults={
            "limit": 25,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["opensky"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.PROVIDER_UNAVAILABLE,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=False,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="callsign", label="Callsign", kind="tag"),
                ColumnSpec(key="origin_country", label="Origin", kind="text"),
                ColumnSpec(key="altitude_ft", label="Altitude", kind="number", unit="ft", format="%.0f"),
                ColumnSpec(key="speed_kt", label="Speed", kind="number", unit="kt", format="%.1f"),
                ColumnSpec(key="heading", label="Heading", kind="number", unit="deg", format="%.0f"),
                ColumnSpec(key="last_contact_utc", label="Last contact (UTC)", kind="datetime"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="aircraft_count", label="Aircraft", kind="kpi"),
                CardSlot(key="source_time", label="Source time", kind="timestamp"),
            ],
        ),
        methodology=(
            "FLY reads the OpenSky /states/all state-vector feed and normalizes each aircraft into "
            "callsign, origin country, last-contact time (UTC), position, altitude (ft), speed (kt), "
            "heading and vertical rate. Positions are ADS-B snapshots. Route origin and destination "
            "are not inferred. OpenSky credentials are optional. An outage or a missing adapter returns "
            "provider_unavailable with rows=[]; no sample aircraft are ever shown."
        ),
        field_dict={
            "rows[].callsign": FieldDef(description="Aircraft callsign reported by ADS-B/OpenSky.", source="opensky"),
            "rows[].origin_country": FieldDef(description="OpenSky origin country field.", source="opensky"),
            "rows[].last_contact_utc": FieldDef(description="Last contact timestamp in UTC.", source="opensky"),
            "rows[].altitude_ft": FieldDef(description="Barometric altitude converted from meters to feet.", unit="ft", source="opensky"),
            "rows[].speed_kt": FieldDef(description="Ground speed converted from m/s to knots.", unit="kt", source="opensky"),
            "rows[].heading": FieldDef(description="True track in degrees clockwise from north.", unit="deg", source="opensky"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fly_unavailable_is_explicit_no_sample_aircraft",
                description="When OpenSky is unavailable or not configured, FLY returns provider_unavailable with rows=[] and no sample aircraft.",
                inputs={},
                assertions=["status_is_provider_unavailable", "rows_is_empty_array"],
            ),
            SemanticTest(
                name="fly_callsign_filter_matches_callsign_only",
                description="With callsign='THY' every returned row has a callsign containing THY.",
                inputs={"callsign": "THY"},
                assertions=["every_row_callsign_contains_THY"],
            ),
            SemanticTest(
                name="fly_invalid_limit_is_input_error",
                description="A non-numeric limit returns input_error naming the limit field, before any provider call.",
                inputs={"limit": "abc"},
                assertions=["status_is_input_error", "opensky_not_called"],
            ),
        ],
    )


__all__ = ["fly"]
