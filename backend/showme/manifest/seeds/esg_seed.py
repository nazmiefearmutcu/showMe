"""ESG — Environment / Social / Governance scoring.

Primary source is Yahoo Finance's sustainability table (Sustainalytics-derived
risk scores, keyless, delayed reference). When Yahoo publishes none for a
ticker the handler falls back to a labelled SEC EDGAR 10-K text proxy
(filing-mention counts, not risk scores). No paid vendor plugin is needed.
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
            "Surface the Yahoo Finance sustainability ESG risk score (Total / E / S / G plus highest "
            "controversy) for a single equity or ETF; when Yahoo publishes none, show a clearly "
            "labelled SEC EDGAR 10-K text proxy instead."
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
                description=(
                    "Accepted for compatibility only: the ESG handler reads the symbol and not this "
                    "input, so it has no effect on the source chain (Yahoo first, then the labelled "
                    "EDGAR proxy)."
                ),
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={"provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["sec_edgar"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.LIVE_OFFICIAL,
                DataMode.NOT_CONFIGURED,
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
            "Primary: Yahoo Finance sustainability table (Sustainalytics-derived ESG risk scores: "
            "total, E, S, G and highest controversy 1-5; lower total = lower unmanaged ESG risk), "
            "keyless, delayed reference (the handler tags these rows source_mode=delayed_reference and "
            "data_mode=delayed_reference; they are not real-time). Fallback when Yahoo publishes "
            "no sustainability table for the ticker: a DERIVED SEC EDGAR proxy counting "
            "environmental, social and governance phrases in 10-K filings from the last 3 years via the keyless "
            "EDGAR full-text search (source_mode=sec_text_proxy, data_mode=live_official: a live fetch of SEC filings, "
            "not a cached snapshot). Proxy values are filing-mention "
            "counts, not risk scores, and are not comparable to vendor ratings. No paid vendor "
            "plugin is required. If neither source responds the status is provider_unavailable "
            "with next_actions."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity or ETF ticker.", source="instrument"),
            "rows": FieldDef(description="Per-pillar rows with scale + source_mode (vendor-risk scale or filing-mention proxy).", source="provider"),
            "totalEsg": FieldDef(description="Yahoo/Sustainalytics total ESG risk score (yfinance path, source_mode=delayed_reference), or on the SEC proxy path (source_mode=sec_text_proxy) the count of unique 10-K filings matching any E/S/G term, not a risk score.", source="provider"),
            "environmentScore": FieldDef(description="E pillar score (vendor score, or proxy mention count).", source="provider"),
            "socialScore": FieldDef(description="S pillar score (vendor score, or proxy mention count).", source="provider"),
            "governanceScore": FieldDef(description="G pillar score (vendor score, or proxy mention count).", source="provider"),
            "controversyLevel": FieldDef(description="Highest active controversy level 1-5 (Yahoo only; null for the proxy).", source="provider"),
            "data_mode": FieldDef(description="delayed_reference (Yahoo) | live_official (EDGAR proxy: live SEC filings, rows labelled sec_text_proxy) | not_configured (no source).", source="envelope"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="esg_no_source_returns_provider_unavailable",
                description="When Yahoo and the EDGAR proxy both fail, the response is status=provider_unavailable with next_actions.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_unavailable_set",
                    "data_mode_in_not_configured_or_live_official",
                    "next_actions_non_empty",
                ],
            ),
            SemanticTest(
                name="esg_sec_proxy_is_labelled_as_counts",
                description="When Yahoo has no sustainability table, rows carry source_mode=sec_text_proxy and the scale says filing mentions (proxy), never a risk score.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "rows_source_mode_in_known_set",
                ],
            ),
            SemanticTest(
                name="esg_methodology_documents_sources",
                description="Methodology must name the Yahoo/Sustainalytics source, the SEC EDGAR proxy fallback and its labelling.",
                inputs={},
                assertions=[
                    "methodology_names_yahoo_sustainalytics_and_sec_proxy",
                ],
            ),
        ],
    )


__all__ = ["esg"]
