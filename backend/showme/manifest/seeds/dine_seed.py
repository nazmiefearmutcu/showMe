"""DINE — Food / restaurant pick utility (non-core).

DINE is an auxiliary off-topic utility that lets the operator stash a
short list of nearby food spots. It is not a finance function and has
no external provider — entries live in the same Round 16 preset
filesystem as other personal lists. DINE is explicitly low-priority in
the cockpit's nav weighting; it belongs in the auxiliary tray, not the
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
def dine() -> FunctionManifest:
    return FunctionManifest(
        code="DINE",
        name="Food Picks",
        category=Category.MISC,
        intent=(
            "Operator-curated short list of nearby food spots — an auxiliary off-topic "
            "utility for the cockpit's miscellaneous tray, not a finance function."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="cuisine",
                label="Cuisine",
                control=ControlKind.SELECT,
                required=False,
                description="Filter the list by cuisine tag.",
                options=["any", "turkish", "italian", "japanese", "mexican", "indian", "cafe"],
            ),
            InputSpec(
                name="price_band",
                label="Price",
                control=ControlKind.SELECT,
                required=False,
                description="Filter by reported price band.",
                options=["any", "$", "$$", "$$$"],
            ),
        ],
        defaults={
            "cuisine": "any",
            "price_band": "any",
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
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="cuisine", label="Cuisine", kind="tag"),
                ColumnSpec(key="price_band", label="Price", kind="tag"),
                ColumnSpec(key="rating", label="Rating", kind="number", format="%.1f"),
                ColumnSpec(key="note", label="Note", kind="text"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="entry_count", label="Entries", kind="kpi"),
                CardSlot(key="top_pick", label="Top pick", kind="badge"),
            ],
        ),
        methodology=(
            "DINE is an auxiliary utility, low nav weight in the finance-first workspace. "
            "It does not belong on the default cockpit grid; it lives in the miscellaneous "
            "tray for operators who want a personal food list inside the same app. There is "
            "no external provider (no Yelp, no Google Places), no network calls, and no "
            "geolocation — entries are operator-supplied and persisted in the Round 16 preset "
            "filesystem alongside other personal lists."
        ),
        field_dict={
            "rows[].name": FieldDef(description="Operator-supplied entry name.", source="store"),
            "rows[].cuisine": FieldDef(description="Optional cuisine tag.", source="store"),
            "rows[].price_band": FieldDef(description="Optional price-band tag.", source="store"),
            "rows[].rating": FieldDef(description="Operator-supplied rating 0..5.", source="store"),
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
                name="dine_returns_only_operator_entries_no_synthetic_seed",
                description="With an empty store, DINE returns rows=[] — it never seeds synthetic restaurant entries.",
                inputs={},
                assertions=["rows_is_empty_array_when_store_empty"],
            ),
            SemanticTest(
                name="dine_filter_cuisine_excludes_others",
                description="With cuisine='italian' every returned row has cuisine == 'italian'.",
                inputs={"cuisine": "italian"},
                assertions=["every_row_cuisine_equals_italian"],
            ),
        ],
    )


__all__ = ["dine"]
