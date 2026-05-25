"""SPLC — Supply Chain (10-K text mining).

There is no free, high-quality supply-chain feed. SPLC pulls the issuer's
most-recent 10-K from SEC EDGAR and exposes a text-mined approximation of
named customers / suppliers (relationship + share of revenue / inputs when
disclosed). Operators are expected to use the result as a starting point,
not a verified bill-of-materials.
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
def splc() -> FunctionManifest:
    return FunctionManifest(
        code="SPLC",
        name="Supply Chain (approximate)",
        category=Category.EQUITIES,
        intent=(
            "Approximate the issuer's supply-chain partners by text-mining the most-recent 10-K — "
            "named customers / suppliers with their disclosed share of revenue or inputs."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker.",
            ),
            InputSpec(
                name="relationship",
                label="Relationship",
                control=ControlKind.SELECT,
                required=False,
                description="Restrict the table to customers, suppliers, or both.",
                options=["both", "customer", "supplier"],
            ),
            InputSpec(
                name="min_pct",
                label="Min disclosed %",
                control=ControlKind.NUMBER,
                required=False,
                description="Drop partners disclosed below this share.",
                min=0,
                max=100,
                step=1,
                unit="%",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "relationship": "both",
            "min_pct": 0,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="sec_edgar",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=86400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "partners", "source_filing"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="partner", label="Partner", kind="text"),
                ColumnSpec(key="relationship", label="Type", kind="tag"),
                ColumnSpec(key="disclosed_pct", label="Disclosed %", kind="percent", format="%.2f"),
                ColumnSpec(key="excerpt", label="Excerpt", kind="text"),
                ColumnSpec(key="source_url", label="Source 10-K", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="partner_count", label="Partners", kind="big_number"),
                CardSlot(key="customer_count", label="Customers", kind="kpi"),
                CardSlot(key="supplier_count", label="Suppliers", kind="kpi"),
                CardSlot(key="source_filing", label="Source 10-K", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "SPLC fetches the issuer's most-recent 10-K via SEC EDGAR, scans the Risk Factors + "
            "Item 1 (Business) + Item 7 (MD&A) sections for sentences that name a counterparty "
            "alongside a relationship keyword (customer / supplier / distributor / OEM) and an "
            "optional percentage figure. The extractor surfaces (partner, relationship, "
            "disclosed_pct, excerpt, source_url) so the operator can read the source. The result "
            "is explicitly approximate — no free supply-chain feed is bundled — and the panel "
            "warns the user to verify before trading on it."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "partners": FieldDef(description="Text-mined supply-chain partner rows.", source="sec_edgar"),
            "partner_count": FieldDef(description="Total partners extracted.", source="computed"),
            "customer_count": FieldDef(description="Partners classified as customers.", source="computed"),
            "supplier_count": FieldDef(description="Partners classified as suppliers.", source="computed"),
            "source_filing": FieldDef(description="Most-recent 10-K accession number.", source="sec_edgar"),
            "source_url": FieldDef(description="Direct EDGAR URL of the source 10-K.", source="sec_edgar"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="splc_aapl_returns_partner_list_or_empty_ok",
                description="SPLC for AAPL returns either an extracted partner list or status=ok with an empty array (not fabricated).",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_ok_set",
                    "partners_is_array",
                    "source_filing_non_empty",
                ],
            ),
            SemanticTest(
                name="splc_relationship_filter_applies",
                description="relationship=customer restricts the table to customer rows.",
                inputs={"symbol": "AAPL", "relationship": "customer"},
                assertions=["all_partners_have_relationship_customer"],
            ),
            SemanticTest(
                name="splc_provider_outage_returns_unavailable",
                description="When EDGAR is unreachable, status=provider_unavailable; no fake partners.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "partners_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["splc"]
