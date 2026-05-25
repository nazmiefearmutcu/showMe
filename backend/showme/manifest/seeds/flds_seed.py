"""FLDS — Searchable field catalog.

The local catalog of every field name accepted by BQL get(...) clauses,
screener DSLs, and advanced analytics params. Pure index — no network
calls, no provider. Companion to BQL (which executes queries against these
fields) and DAPI (which surfaces the routes that consume them).
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
def flds() -> FunctionManifest:
    return FunctionManifest(
        code="FLDS",
        name="Field Lookup",
        category=Category.API_DEV,
        intent=(
            "Search the local ShowMe field catalog by name, description, or category — the "
            "authoritative index of fields that BQL, screeners, and analytics params accept."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.OPTION,
        ],
        inputs=[
            InputSpec(
                name="prefix",
                label="Search",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Substring matched against the field name, description, and category. "
                    "Empty returns the full catalog."
                ),
            ),
            InputSpec(
                name="category",
                label="Category",
                control=ControlKind.SELECT,
                required=False,
                description="Restrict results to one functional grouping.",
                options=[
                    "market",
                    "valuation",
                    "statement",
                    "technical",
                    "option",
                    "risk",
                    "fixed_income",
                    "general",
                ],
            ),
            InputSpec(
                name="limit",
                label="Max rows",
                control=ControlKind.NUMBER,
                required=False,
                description="Cap on rows returned.",
                min=1.0,
                max=100.0,
                step=10.0,
            ),
        ],
        defaults={
            "prefix": "",
            "limit": 50,
        },
        # Pure local index — no provider, no network.
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.MODELED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["rows", "summary", "field_dictionary"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="field", label="Field", kind="text"),
                ColumnSpec(key="category", label="Category", kind="tag"),
                ColumnSpec(key="description", label="Description", kind="text"),
                ColumnSpec(key="example", label="Example", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matched", label="Matched", kind="big_number"),
                CardSlot(key="shown", label="Shown", kind="kpi"),
                CardSlot(key="catalog_fields", label="Catalog size", kind="kpi"),
                CardSlot(key="query", label="Query", kind="badge"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FLDS searches the local ShowMe field catalog by field name, description, and category. "
            "The catalog is an in-process dictionary that maps user-visible field names to supported "
            "function contexts (BQL get clauses, screener DSL filters, analytics advanced params). "
            "It is not a live market-data request and never reaches any provider. Matching uses a "
            "case-insensitive substring against the concatenated field+description+category haystack, "
            "with field-name prefix matches always included even when the substring is elsewhere. "
            "Companion to BQL (which executes queries against these fields) and DAPI (which lists "
            "the routes that consume them)."
        ),
        field_dict={
            "rows[].field": FieldDef(description="Canonical field name accepted by BQL/screeners/analytics.", source="catalog"),
            "rows[].category": FieldDef(description="market/valuation/statement/technical/option/risk/fixed_income/general.", source="catalog"),
            "rows[].description": FieldDef(description="Plain-language meaning of the field.", source="catalog"),
            "rows[].example": FieldDef(description="One concrete place the field can be used.", source="catalog"),
            "summary.matched": FieldDef(unit="count", description="Total matches before limit.", source="flds"),
            "summary.shown": FieldDef(unit="count", description="Rows returned after limit.", source="flds"),
            "summary.catalog_fields": FieldDef(unit="count", description="Total fields in the catalog.", source="flds"),
            "summary.query": FieldDef(description="Echo of the search prefix.", source="flds"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        semantic_tests=[
            SemanticTest(
                name="flds_empty_query_returns_full_catalog",
                description="prefix='' returns up to limit rows representative of the full catalog.",
                inputs={"prefix": "", "limit": 50},
                assertions=[
                    "rows_length_at_most_50",
                    "summary.catalog_fields >= rows_length",
                ],
            ),
            SemanticTest(
                name="flds_prefix_filter_narrows_results",
                description="prefix='close' returns only rows that match close in field, description, or category.",
                inputs={"prefix": "close"},
                assertions=[
                    "every_row_matches_close_in_field_or_description_or_category",
                ],
            ),
            SemanticTest(
                name="flds_no_network_call",
                description="FLDS never calls any market-data provider; the catalog is in-process only.",
                inputs={},
                assertions=[
                    "no_provider_request_made",
                ],
            ),
            SemanticTest(
                name="flds_limit_respected",
                description="limit=5 returns at most 5 rows even when many match.",
                inputs={"prefix": "", "limit": 5},
                assertions=["rows_length_at_most_5"],
            ),
        ],
    )


__all__ = ["flds"]
