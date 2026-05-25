"""ESG — Environment / Social / Governance scoring.

No real ESG vendor is wired into the showMe adapter list, so the manifest
declares primary=internal and pegs acceptable_modes to NOT_CONFIGURED + a
cached snapshot for any vendor data the operator has loaded manually. The
methodology explains the gap: a paid vendor plugin must be wired to return
LIVE_OFFICIAL.
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
def esg() -> FunctionManifest:
    return FunctionManifest(
        code="ESG",
        name="ESG Scores",
        category=Category.EQUITIES,
        intent=(
            "Surface vendor ESG scores (Total / E / S / G) plus controversy level for a single "
            "equity or ETF when a real ESG provider plugin is configured."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity or ETF ticker.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.CACHED_SNAPSHOT.value,
                    DataMode.NOT_CONFIGURED.value,
                ],
            ),
        ],
        defaults={"provider_mode": DataMode.NOT_CONFIGURED.value},
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.NOT_CONFIGURED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=86400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="pillar", label="Pillar", kind="text"),
                ColumnSpec(key="score", label="Score", kind="number", format="%.2f"),
                ColumnSpec(key="scale", label="Scale", kind="text"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="totalEsg", label="Total ESG", kind="big_number"),
                CardSlot(key="environmentScore", label="E", kind="kpi"),
                CardSlot(key="socialScore", label="S", kind="kpi"),
                CardSlot(key="governanceScore", label="G", kind="kpi"),
                CardSlot(key="controversyLevel", label="Controversy", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ESG requires a paid vendor plugin (Sustainalytics / MSCI / Refinitiv) — none is "
            "bundled with showMe. The handler probes the configured ESG adapter and returns Total, "
            "E, S, G, and controversy level when available. With no plugin configured the response "
            "is status=provider_unavailable with data_mode=not_configured and a next_actions list "
            "explaining how to wire a vendor. yfinance's sustainability blob may be cached as a "
            "best-effort snapshot fallback but is signalled via source_mode=cached_snapshot and "
            "should not be treated as a live score."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity or ETF ticker.", source="instrument"),
            "rows": FieldDef(description="Per-pillar score rows with scale + source_mode.", source="provider"),
            "totalEsg": FieldDef(description="Composite ESG risk / opportunity score.", source="provider"),
            "environmentScore": FieldDef(description="E pillar score.", source="provider"),
            "socialScore": FieldDef(description="S pillar score.", source="provider"),
            "governanceScore": FieldDef(description="G pillar score.", source="provider"),
            "controversyLevel": FieldDef(description="Numeric or labelled controversy level.", source="provider"),
            "data_mode": FieldDef(description="not_configured | cached_snapshot.", source="envelope"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="esg_no_vendor_returns_not_configured",
                description="With no ESG vendor plugin wired, the response is status=provider_unavailable / mode=not_configured.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_unavailable_set",
                    "data_mode_in_not_configured_or_cached_snapshot",
                    "next_actions_non_empty",
                ],
            ),
            SemanticTest(
                name="esg_cached_snapshot_passes_through_when_available",
                description="If a cached snapshot exists (e.g. from yfinance sustainability), it is returned with source_mode=cached_snapshot.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "rows_source_mode_in_known_set",
                ],
            ),
            SemanticTest(
                name="esg_methodology_documents_vendor_gap",
                description="Methodology must explicitly state that ESG needs a paid vendor plugin.",
                inputs={},
                assertions=[
                    "methodology_mentions_paid_vendor_plugin",
                ],
            ),
        ],
    )


__all__ = ["esg"]
