"""PIB — Public Information Book.

Aggregates the issuer's recent SEC filings into a single chronological
"public info book": 10-K, 10-Q, 8-K, DEF 14A, 13D/G, S-1. Backed by SEC EDGAR
only; the AI summary is not implemented (summary_status not_implemented).
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
def pib() -> FunctionManifest:
    return FunctionManifest(
        code="PIB",
        name="Public Information Book",
        category=Category.EQUITIES,
        intent=(
            "Compile a chronological book of the issuer's public filings (10-K, 10-Q, 8-K, DEF 14A, "
            "13D/G, S-1). An AI summary is planned but not implemented: include_summary reports summary_status not_implemented."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker.",
            ),
            InputSpec(
                name="months",
                label="History (months)",
                control=ControlKind.NUMBER,
                required=False,
                description="Lookback for the filing list.",
                min=1,
                max=24,
                step=1,
                unit="months",
            ),
            InputSpec(
                name="form_types",
                label="Form types",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to a subset of form types.",
                options=["10-K", "10-Q", "8-K", "DEF 14A", "13D", "13G", "S-1", "S-4", "20-F"],
            ),
            InputSpec(
                name="include_summary",
                label="AI summary",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Requests an AI summary. Not implemented yet: the response sets summary_status to not_implemented and attaches no summary.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description=(
                    "Accepted for compatibility only: the sole source is SEC EDGAR (live official "
                    "filings); the handler does not read this input."
                ),
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                ],
            ),
        ],
        defaults={
            "months": 6,
            "include_summary": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="sec_edgar",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "filings"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="filingDate", label="Filed", kind="date"),
                ColumnSpec(key="reportDate", label="Reported", kind="date"),
                ColumnSpec(key="form", label="Form", kind="tag"),
                ColumnSpec(key="accession", label="Accession", kind="text"),
                ColumnSpec(key="url", label="Filing", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="filing_count", label="Filings", kind="big_number"),
                CardSlot(key="latest_form", label="Latest form", kind="badge"),
                CardSlot(key="latest_filing_date", label="Latest", kind="timestamp"),
                CardSlot(key="summary", label="Summary", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "PIB walks SEC EDGAR for the issuer's recent filings within the lookback window. Each "
            "row carries symbol, section, form, filingDate, reportDate, accession, url (the absolute "
            "EDGAR primary-document link, or null when the CIK is unknown) and source_mode. Rows are "
            "ranked by filingDate descending. The months and form_types filters are applied "
            "server-side before the row cap. include_summary is not implemented: the handler reports "
            "summary_status not_implemented and attaches no summary text."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "filings": FieldDef(description="Chronological filings list.", source="sec_edgar"),
            "filing_count": FieldDef(description="Total filings in the lookback window.", source="computed"),
            "latest_filing_date": FieldDef(description="Most-recent filing date.", source="computed"),
            "summary": FieldDef(description="AI summary of recent material disclosures; always null until implemented.", source="not_implemented"),
            "rows[].url": FieldDef(description="Direct EDGAR primary-document URL (CIK, accession and document name).", source="sec_edgar"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="pib_aapl_returns_filings_list",
                description="PIB for AAPL returns at least one filing row with form_type + URL.",
                inputs={"symbol": "AAPL", "months": 6},
                assertions=[
                    "status_in_ok_set",
                    "filings_non_empty",
                    "filings_have_filing_url",
                ],
            ),
            SemanticTest(
                name="pib_form_filter_applies",
                description="form_types=['10-K'] restricts the table to 10-K rows.",
                inputs={"symbol": "AAPL", "form_types": ["10-K"]},
                assertions=["all_filings_have_form_type_10K"],
            ),
            SemanticTest(
                name="pib_provider_outage_returns_unavailable",
                description="When EDGAR is unreachable, status=provider_unavailable; no fake filings.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "filings_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["pib"]
