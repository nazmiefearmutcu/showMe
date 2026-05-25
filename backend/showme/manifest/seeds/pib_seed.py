"""PIB — Public Information Book.

Aggregates the issuer's recent SEC filings into a single chronological
"public info book": 10-K, 10-Q, 8-K, DEF 14A, 13D/G, S-1, plus an optional
AI-generated summary stub. Backed by SEC EDGAR (primary) with yfinance
news / actions as best-effort context.
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
            "13D/G, S-1) and a brief AI summary of the most recent material disclosures."
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
                description="When true the handler attaches a short summary of the most recent material filings.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "months": 6,
            "include_summary": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["sec_edgar", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
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
                ColumnSpec(key="filing_date", label="Date", kind="date"),
                ColumnSpec(key="form_type", label="Form", kind="tag"),
                ColumnSpec(key="description", label="Description", kind="text"),
                ColumnSpec(key="filing_url", label="Filing", kind="action"),
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
            "row is normalized into (filing_date, form_type, description, filing_url) and ranked "
            "by filing date descending. The form_types filter is applied server-side. When "
            "include_summary=true the handler attaches a short paragraph summarizing the most "
            "recent 8-K / 10-K / DEF 14A items — this is an opt-in AI step and disabled by "
            "default so the panel works without an LLM credential."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "filings": FieldDef(description="Chronological filings list.", source="sec_edgar"),
            "filing_count": FieldDef(description="Total filings in the lookback window.", source="computed"),
            "latest_filing_date": FieldDef(description="Most-recent filing date.", source="computed"),
            "summary": FieldDef(description="Optional AI summary of recent material disclosures.", source="llm"),
            "filing_url": FieldDef(description="Direct EDGAR document URL.", source="sec_edgar"),
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
