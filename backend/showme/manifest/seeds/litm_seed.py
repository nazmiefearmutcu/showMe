"""LITM — Litigation Matters (8-K & 10-K Item 3 extraction).

Surfaces material legal proceedings from 8-K Item 1.01 / Item 8.01 filings
plus 10-K Item 3 (Legal Proceedings) text. SEC EDGAR is primary; the
handler ranks by filing date and exposes the source filing URL.
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
def litm() -> FunctionManifest:
    return FunctionManifest(
        code="LITM",
        name="Litigation Matters",
        category=Category.EQUITIES,
        intent=(
            "Surface material legal proceedings disclosed in 8-K and 10-K filings, ranked by "
            "filing date with the source document URL."
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
                name="months",
                label="History (months)",
                control=ControlKind.NUMBER,
                required=False,
                description="Lookback for the litigation history.",
                min=3,
                max=60,
                step=1,
                unit="months",
            ),
            InputSpec(
                name="severity",
                label="Min severity",
                control=ControlKind.SELECT,
                required=False,
                description="Minimum severity bucket (rough heuristic from disclosure size + keywords).",
                options=["low", "medium", "high", "critical"],
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
            "months": 24,
            "severity": "low",
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
        caching=CachingPolicy(ttl_seconds=14400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "matters"],
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
                ColumnSpec(key="severity", label="Severity", kind="tag"),
                ColumnSpec(key="summary", label="Summary", kind="text"),
                ColumnSpec(key="filing_url", label="Filing", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matter_count", label="Matters", kind="big_number"),
                CardSlot(key="latest_severity", label="Latest severity", kind="badge"),
                CardSlot(key="latest_filing_date", label="Latest", kind="timestamp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "LITM walks SEC EDGAR for the issuer's 8-K filings (Item 1.01 and Item 8.01 are the "
            "common loci for litigation disclosure) plus the most-recent 10-K's Item 3 (Legal "
            "Proceedings) section. Each matter is normalized into (filing_date, form_type, "
            "summary, severity, filing_url). Severity is a heuristic bucket (keyword density + "
            "disclosure size) and is explicitly approximate — operators are expected to read the "
            "linked filings. The min-severity filter is applied server-side. When no relevant "
            "filings exist in the window, status=ok with an empty matters array (not unavailable)."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "matters": FieldDef(description="Normalized list of disclosed litigation matters.", source="sec_edgar"),
            "matter_count": FieldDef(description="Total matters in the lookback window.", source="computed"),
            "severity": FieldDef(description="low | medium | high | critical (heuristic).", source="computed"),
            "latest_filing_date": FieldDef(description="Most-recent litigation-related filing date.", source="computed"),
            "filing_url": FieldDef(description="Direct EDGAR document URL for the source filing.", source="sec_edgar"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="litm_aapl_returns_matter_list_or_empty_ok",
                description="LITM for AAPL returns either a matter list or status=ok with an empty array (not unavailable).",
                inputs={"symbol": "AAPL", "months": 24},
                assertions=[
                    "status_in_ok_set",
                    "matters_is_array",
                ],
            ),
            SemanticTest(
                name="litm_severity_filter_applies",
                description="severity='high' restricts the table to high+ rows.",
                inputs={"symbol": "AAPL", "severity": "high"},
                assertions=["all_matters_severity_at_least_high"],
            ),
            SemanticTest(
                name="litm_provider_outage_returns_unavailable",
                description="When EDGAR is unreachable, status=provider_unavailable; no fake matters.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "matters_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["litm"]
