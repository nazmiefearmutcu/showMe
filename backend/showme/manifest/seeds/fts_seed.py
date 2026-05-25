"""FTS — SEC EDGAR Full-Text Search.

Cross-issuer free-text search across 10-K / 10-Q / 8-K / S-1 etc. Backed by
the EDGAR Full-Text Search API (`sec_efts`). The handler scopes the query
to the active symbol when one is selected, and exposes form-type + date
filters.
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
def fts() -> FunctionManifest:
    return FunctionManifest(
        code="FTS",
        name="SEC Full-Text Search",
        category=Category.EQUITIES,
        intent=(
            "Search SEC EDGAR filings by free text, scoped optionally by form type, date range, "
            "and (if selected) issuer symbol — surfaces a ranked filing list with excerpts."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="query",
                label="Query",
                control=ControlKind.TEXT,
                required=True,
                description="Free-text search expression (EDGAR Full-Text syntax supported).",
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Optional issuer filter; pre-pended to the query when present.",
            ),
            InputSpec(
                name="forms",
                label="Form types",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to a subset of form types.",
                options=["10-K", "10-Q", "8-K", "S-1", "DEF 14A", "20-F", "6-K"],
            ),
            InputSpec(
                name="date_from",
                label="From",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Lower bound for filing date (inclusive).",
            ),
            InputSpec(
                name="date_to",
                label="To",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Upper bound for filing date (inclusive).",
            ),
            InputSpec(
                name="live",
                label="Live mode",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true the handler hits the EDGAR EFTS endpoint; otherwise a template stub.",
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
            "query": "risk factors",
            "live": True,
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
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["status", "query", "rows", "total_hits"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="filing_date", label="Date", kind="date"),
                ColumnSpec(key="issuer", label="Issuer", kind="text"),
                ColumnSpec(key="form_type", label="Form", kind="tag"),
                ColumnSpec(key="excerpt", label="Excerpt", kind="text"),
                ColumnSpec(key="filing_url", label="Filing", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_hits", label="Hits", kind="big_number"),
                CardSlot(key="query", label="Query", kind="badge"),
                CardSlot(key="returned", label="Returned", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FTS calls the SEC EDGAR Full-Text Search API with the user's free-text query, "
            "optionally narrowed by form types and a [date_from, date_to] window. When a symbol "
            "is selected the issuer ticker is prepended to the query so results stay scoped. "
            "Each hit row carries (filing_date, issuer, form_type, excerpt, filing_url) so the "
            "operator can deep-link into the document. live=false returns a small template stub "
            "for offline panel rendering without hitting EDGAR."
        ),
        field_dict={
            "query": FieldDef(description="Resolved query string actually sent to EDGAR EFTS.", source="input"),
            "total_hits": FieldDef(description="Total hits reported by EDGAR (may exceed returned rows).", source="provider"),
            "returned": FieldDef(description="Rows actually returned to the UI (capped page size).", source="provider"),
            "rows": FieldDef(description="Ranked filing rows with excerpt + URL.", source="provider"),
            "filing_url": FieldDef(description="Direct EDGAR document URL.", source="provider"),
            "form_type": FieldDef(description="Form code (10-K / 10-Q / 8-K ...).", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fts_risk_factors_returns_hits",
                description="FTS query 'risk factors' against AAPL returns ranked rows.",
                inputs={"query": "risk factors", "symbol": "AAPL", "live": True},
                assertions=[
                    "status_in_ok_set",
                    "rows_non_empty",
                    "rows_have_filing_url",
                ],
            ),
            SemanticTest(
                name="fts_form_filter_applies",
                description="Restricting forms=['10-K'] returns only 10-K rows.",
                inputs={"query": "supply chain", "forms": ["10-K"]},
                assertions=["all_rows_have_form_type_10K"],
            ),
            SemanticTest(
                name="fts_provider_outage_returns_unavailable",
                description="When EDGAR EFTS is unreachable, status=provider_unavailable; no fake hits.",
                inputs={"query": "doesnotexist_xyz", "live": True},
                assertions=[
                    "status_in_unavailable_or_empty_set",
                    "rows_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["fts"]
