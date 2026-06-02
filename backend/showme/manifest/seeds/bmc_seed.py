"""BMC — Brand / marketing / community metrics ("build my custom").

BMC is a placeholder pane that lets the operator wire up custom KPI
tiles (brand mention count, community sentiment, marketing pipeline,
etc.) from arbitrary internal sources. It owns no provider on its own
and is a strong relocation candidate — once any of the wired metrics
becomes a first-class data type, those rows should be lifted into their
own dedicated pane.
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
def bmc() -> FunctionManifest:
    return FunctionManifest(
        code="BMC",
        name="Build My Custom (Brand / Marketing / Community)",
        category=Category.MISC,
        intent=(
            "Operator-wired KPI tiles for brand / marketing / community metrics — a thin "
            "internal aggregator with no external provider, intended as a relocation "
            "candidate once individual metrics earn their own first-class panes."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="layout",
                label="Layout",
                control=ControlKind.SELECT,
                required=True,
                description="Tile layout preset.",
                options=["compact", "comfortable", "wall"],
            ),
            InputSpec(
                name="sources",
                label="Sources",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Wired internal sources for the KPI tiles.",
                options=["watchlist_count", "alert_count", "bot_pnl", "news_volume", "manual_kpi"],
            ),
        ],
        defaults={
            "layout": "comfortable",
            "sources": ["watchlist_count", "alert_count"],
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=30, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="key", label="Metric", kind="text"),
                ColumnSpec(key="label", label="Label", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.2f"),
                ColumnSpec(key="unit", label="Unit", kind="tag"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="tile_count", label="Tiles", kind="kpi"),
                CardSlot(key="layout", label="Layout", kind="badge"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BMC is an operator-wired aggregator: it reads counts and aggregates from already-"
            "registered ShowMe stores (WATCH counts, ALRT active count, BOT PnL, TOP item "
            "volume) and renders them as configurable KPI tiles. There is no external "
            "provider; data freshness mirrors the upstream source's TTL. BMC is a relocation "
            "candidate — once a wired metric earns enough operator attention to deserve its "
            "own pane (e.g. brand mention sentiment as a real news_intel function), those "
            "tiles should be lifted into a dedicated MISC->NEWS_INTEL pane and removed here."
        ),
        field_dict={
            "rows[].key": FieldDef(description="Internal metric key.", source="store"),
            "rows[].label": FieldDef(description="Operator-supplied tile label.", source="config"),
            "rows[].value": FieldDef(description="Aggregated metric value at refresh time.", source="aggregator"),
            "rows[].unit": FieldDef(description="Metric unit if applicable.", source="config"),
        },
        provenance=ProvenanceSpec(
            require_source_list=False,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="bmc_empty_sources_returns_empty_rows_not_error",
                description="With sources=[] the aggregator returns rows=[] and tile_count=0 — never a synthetic placeholder tile.",
                inputs={"sources": []},
                assertions=[
                    "rows_is_empty_array",
                    "tile_count_equals_zero",
                    "no_top_level_error",
                ],
            ),
            SemanticTest(
                name="bmc_reads_through_to_existing_stores",
                description="With sources=['watchlist_count'] the row's value matches the live WATCH store length.",
                inputs={"sources": ["watchlist_count"]},
                assertions=["watchlist_count_value_matches_watch_store"],
            ),
        ],
    )


__all__ = ["bmc"]
