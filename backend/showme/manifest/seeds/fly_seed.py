"""FLY — Travel / flight pick utility (non-core).

FLY is an auxiliary off-topic utility that lets the operator stash a
short list of travel ideas (flights, hotels, trip notes). It is not a
finance function and has no external provider — entries live in the
Round 16 preset filesystem. FLY is explicitly low-priority in the
cockpit's nav weighting; it belongs in the auxiliary tray, not the
finance-first workspace default.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
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
        name="Travel Picks",
        category=Category.MISC,
        intent=(
            "Operator-curated short list of travel ideas (flights, hotels, trip notes) — "
            "an auxiliary off-topic utility for the cockpit's miscellaneous tray, not a "
            "finance function."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="kind",
                label="Kind",
                control=ControlKind.SELECT,
                required=False,
                description="Filter by entry kind.",
                options=["any", "flight", "hotel", "rental", "note"],
            ),
            InputSpec(
                name="destination",
                label="Destination",
                control=ControlKind.TEXT,
                required=False,
                description="Free-text destination filter (case-insensitive contains).",
            ),
        ],
        defaults={
            "kind": "any",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.CACHED_SNAPSHOT,
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
            next_actions=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="kind", label="Kind", kind="tag"),
                ColumnSpec(key="destination", label="Destination", kind="text"),
                ColumnSpec(key="when", label="When", kind="date"),
                ColumnSpec(key="cost", label="Cost", kind="currency", format="%.2f"),
                ColumnSpec(key="note", label="Note", kind="text"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="entry_count", label="Entries", kind="kpi"),
                CardSlot(key="next_trip", label="Next trip", kind="timestamp"),
            ],
        ),
        methodology=(
            "FLY is an auxiliary utility, low nav weight in the finance-first workspace. "
            "It does not belong on the default cockpit grid; it lives in the miscellaneous "
            "tray for operators who want a personal travel list inside the same app. There "
            "is no external provider (no Skyscanner / Kayak / Booking integration), no "
            "network calls, and no live pricing — entries are operator-supplied and "
            "persisted in the Round 16 preset filesystem alongside other personal lists."
        ),
        field_dict={
            "rows[].kind": FieldDef(description="flight / hotel / rental / note.", source="store"),
            "rows[].destination": FieldDef(description="Free-text destination.", source="store"),
            "rows[].when": FieldDef(description="Optional departure / start date.", source="store"),
            "rows[].cost": FieldDef(description="Operator-supplied cost estimate.", source="store"),
            "rows[].note": FieldDef(description="Free-text note.", source="store"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fly_returns_only_operator_entries_no_synthetic_seed",
                description="With an empty store, FLY returns rows=[] — it never seeds synthetic flights or hotels.",
                inputs={},
                assertions=["rows_is_empty_array_when_store_empty"],
            ),
            SemanticTest(
                name="fly_filter_kind_excludes_others",
                description="With kind='flight' every returned row has kind == 'flight'.",
                inputs={"kind": "flight"},
                assertions=["every_row_kind_equals_flight"],
            ),
        ],
    )


__all__ = ["fly"]
