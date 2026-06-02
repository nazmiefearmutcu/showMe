"""GRAB — Shopping / errand pick utility (non-core).

GRAB is an auxiliary off-topic utility that lets the operator stash a
short shopping or errand list. It is not a finance function and has no
external provider — entries live in the Round 16 preset filesystem.
GRAB is explicitly low-priority in the cockpit's nav weighting; it
belongs in the auxiliary tray, not the finance-first workspace default.
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
def grab() -> FunctionManifest:
    return FunctionManifest(
        code="GRAB",
        name="Shopping / Errands",
        category=Category.MISC,
        intent=(
            "Operator-curated short shopping / errand list — an auxiliary off-topic utility "
            "for the cockpit's miscellaneous tray, not a finance function."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="status",
                label="Status",
                control=ControlKind.SELECT,
                required=False,
                description="Filter by completion state.",
                options=["any", "open", "done"],
            ),
            InputSpec(
                name="tag",
                label="Tag",
                control=ControlKind.TEXT,
                required=False,
                description="Filter by free-text tag (e.g. groceries, hardware).",
            ),
        ],
        defaults={
            "status": "open",
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
                ColumnSpec(key="item", label="Item", kind="text"),
                ColumnSpec(key="quantity", label="Qty", kind="number", format="%d"),
                ColumnSpec(key="tag", label="Tag", kind="tag"),
                ColumnSpec(key="status", label="Status", kind="tag"),
                ColumnSpec(key="added_at", label="Added", kind="datetime", format="rel"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="open_count", label="Open", kind="kpi"),
                CardSlot(key="done_count", label="Done", kind="kpi"),
                CardSlot(key="total_count", label="Total", kind="kpi"),
            ],
        ),
        methodology=(
            "GRAB is an auxiliary utility, low nav weight in the finance-first workspace. "
            "It does not belong on the default cockpit grid; it lives in the miscellaneous "
            "tray for operators who want a personal errand list inside the same app. There "
            "is no external provider (no Amazon / Instacart integration), no network calls, "
            "and no price lookups — entries are operator-supplied and persisted in the "
            "Round 16 preset filesystem alongside other personal lists."
        ),
        field_dict={
            "rows[].item": FieldDef(description="Free-text item name.", source="store"),
            "rows[].quantity": FieldDef(description="Optional integer quantity.", source="store"),
            "rows[].tag": FieldDef(description="Optional grouping tag.", source="store"),
            "rows[].status": FieldDef(description="open | done.", source="store"),
            "rows[].added_at": FieldDef(unit="iso8601", description="Add timestamp.", source="store"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="grab_returns_only_operator_entries_no_synthetic_seed",
                description="With an empty store, GRAB returns rows=[] — it never seeds synthetic items.",
                inputs={},
                assertions=["rows_is_empty_array_when_store_empty"],
            ),
            SemanticTest(
                name="grab_filter_status_open_excludes_done",
                description="With status='open' every returned row has status == 'open'.",
                inputs={"status": "open"},
                assertions=["every_row_status_equals_open"],
            ),
        ],
    )


__all__ = ["grab"]
