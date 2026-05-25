"""APPL — Applicable Filings / Company Profile (extended).

Lightweight "company applicable info" pane: takes the canonical DES profile
and layers on the most recent SEC filing pointers + applicable regulatory
classifications (SIC, GICS, primary exchange, fiscal-year end). yfinance is
primary; SEC EDGAR fills in CIK + filing index when available.
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
def appl() -> FunctionManifest:
    return FunctionManifest(
        code="APPL",
        name="Applicable Info",
        category=Category.EQUITIES,
        intent=(
            "Show applicable regulatory / classification info for a company: SIC, GICS sector & "
            "industry, primary exchange, fiscal year end, CIK, and the latest filing pointers."
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
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={"provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["sec_edgar", "openfigi", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
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
                ColumnSpec(key="label", label="Field", kind="text"),
                ColumnSpec(key="value", label="Value", kind="text"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbol", label="Symbol", kind="big_number"),
                CardSlot(key="cik", label="CIK", kind="badge"),
                CardSlot(key="sic_code", label="SIC", kind="badge"),
                CardSlot(key="exchange_name", label="Exchange", kind="badge"),
                CardSlot(key="fiscal_year_end", label="FY end", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "APPL stitches the yfinance company profile (sector / industry / fiscal year end / "
            "exchange) with SEC EDGAR identifiers (CIK + SIC code) so the operator can copy paste "
            "regulatory keys into other tools. When the provider chain falls through, status is "
            "set to provider_unavailable rather than a fake CIK."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "cik": FieldDef(description="SEC Central Index Key.", source="sec_edgar"),
            "sic_code": FieldDef(description="SIC industry classification code.", source="sec_edgar"),
            "exchange_name": FieldDef(description="Humanized primary exchange.", source="EXCHANGE_LEGEND"),
            "fiscal_year_end": FieldDef(description="Month-day fiscal year end (e.g. 0930).", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="appl_aapl_returns_applicable_info",
                description="APPL for AAPL returns CIK + SIC + fiscal year end with status=ok.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_ok_set",
                    "cik_non_empty",
                    "rows_non_empty",
                ],
            ),
            SemanticTest(
                name="appl_provider_outage_does_not_fabricate_cik",
                description="When providers fail, status=provider_unavailable with next_actions; CIK is null not stubbed.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "no_synthetic_cik",
                    "next_actions_non_empty",
                ],
            ),
        ],
    )


__all__ = ["appl"]
