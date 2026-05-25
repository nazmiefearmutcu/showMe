"""ISIN — Symbol cross-reference (ISIN / CUSIP / SEDOL / Ticker → OpenFIGI).

Resolves any of the canonical identifier flavours into the OpenFIGI
master record plus cross-IDs. OpenFIGI is the declared primary; absence
of the adapter degrades to ``provider_unavailable`` rather than guessing.
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
def isin() -> FunctionManifest:
    return FunctionManifest(
        code="ISIN",
        name="Symbol Cross-Reference",
        category=Category.API_DEV,
        intent=(
            "Resolve ISIN / CUSIP / SEDOL / Ticker identifiers into the OpenFIGI canonical "
            "record plus cross-identifiers — the bridge for instrument lookups across venues."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.BOND,
            AssetClass.OPTION,
            AssetClass.FUTURE,
        ],
        inputs=[
            InputSpec(
                name="ids",
                label="Identifiers",
                control=ControlKind.TEXT,
                required=True,
                description=(
                    "One or more identifiers (comma-separated string or list). Type is "
                    "auto-detected when id_type is omitted."
                ),
            ),
            InputSpec(
                name="id_type",
                label="ID type",
                control=ControlKind.SELECT,
                required=False,
                description="Force the identifier flavour; otherwise auto-detected per row.",
                options=["ID_ISIN", "ID_CUSIP", "ID_SEDOL", "TICKER"],
            ),
            InputSpec(
                name="limit",
                label="Max matches per ID",
                control=ControlKind.NUMBER,
                required=False,
                description="Per-input cap on OpenFIGI matches; 1..100.",
                min=1.0,
                max=100.0,
                step=5.0,
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
            "limit": 25,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        # OpenFIGI is the declared primary — the manifest contract pins it
        # so the rebuild cannot silently swap in a heuristic resolver.
        provider_chain=ProviderChain(
            primary="openfigi",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=86400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="input", label="Input", kind="text"),
                ColumnSpec(key="id_type", label="Type", kind="tag"),
                ColumnSpec(key="rank", label="Rank", kind="text"),
                ColumnSpec(key="figi", label="FIGI", kind="text"),
                ColumnSpec(key="ticker", label="Ticker", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="market_sector", label="Sector", kind="tag"),
                ColumnSpec(key="security_type", label="Security", kind="tag"),
                ColumnSpec(key="security_type2", label="Sub-type", kind="tag"),
                ColumnSpec(key="exchange_code", label="Exchange", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="inputs_resolved", label="Resolved", kind="big_number"),
                CardSlot(key="inputs_failed", label="Failed", kind="kpi"),
                CardSlot(key="matches", label="Matches", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ISIN auto-detects each input's identifier flavour (ISIN = 12 alnum with leading "
            "country code; CUSIP = 9 alnum with check digit; SEDOL = 7 alnum, last numeric, no "
            "vowels in first 6; otherwise TICKER) unless id_type forces a flavour. Each input is "
            "passed to the OpenFIGI lookup_by(id_type, id_value) call; up to `limit` matches per "
            "input are returned with rank annotations. Per-input lookup failures are recorded as "
            "warnings without dropping successful resolutions. When the OpenFIGI adapter is not "
            "configured, ISIN returns status=provider_unavailable with rows=[] and an actionable "
            "next-action rather than guessing or returning a ticker-only fallback. Resolved rows "
            "are cacheable for 24h because OpenFIGI's master records are stable."
        ),
        field_dict={
            "rows[].input": FieldDef(description="Echo of the caller-supplied identifier.", source="isin"),
            "rows[].id_type": FieldDef(description="Resolved identifier flavour (auto-detected or forced).", source="isin"),
            "rows[].rank": FieldDef(description="#1 / #2 / ... — rank within the per-input matches.", source="isin"),
            "rows[].figi": FieldDef(description="OpenFIGI Financial Instrument Global Identifier.", source="openfigi"),
            "rows[].ticker": FieldDef(description="Canonical ticker on the venue.", source="openfigi"),
            "rows[].name": FieldDef(description="Issuer/instrument name.", source="openfigi"),
            "rows[].market_sector": FieldDef(description="Market sector classifier (Equity, Corp, Govt, ...).", source="openfigi"),
            "rows[].security_type": FieldDef(description="OpenFIGI security type.", source="openfigi"),
            "rows[].security_type2": FieldDef(description="OpenFIGI sub-type.", source="openfigi"),
            "rows[].exchange_code": FieldDef(description="MIC or OpenFIGI exchange code.", source="openfigi"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        semantic_tests=[
            SemanticTest(
                name="isin_resolves_known_isin",
                description="A known ISIN like US0378331005 resolves to the AAPL master record with figi+ticker populated.",
                inputs={"ids": "US0378331005"},
                assertions=[
                    "rows_length_at_least_1",
                    "first_row_figi_non_empty",
                    "first_row_ticker_equals_AAPL",
                ],
            ),
            SemanticTest(
                name="isin_auto_detects_id_type",
                description="Without id_type, ISIN classifies 'US0378331005' as ID_ISIN and a 9-char alnum as ID_CUSIP.",
                inputs={"ids": "US0378331005"},
                assertions=[
                    "first_row_id_type == 'ID_ISIN'",
                ],
            ),
            SemanticTest(
                name="isin_no_openfigi_adapter_provider_unavailable",
                description="With no OpenFIGI adapter wired, ISIN returns status=provider_unavailable and rows=[].",
                inputs={"ids": "AAPL"},
                assertions=[
                    "status == 'provider_unavailable'",
                    "rows == []",
                    "data_mode in {'not_configured', 'provider_unavailable'}",
                ],
            ),
            SemanticTest(
                name="isin_no_silent_ticker_fallback",
                description="ISIN must not return a ticker-only guess when OpenFIGI returns no matches — the row reports failure honestly.",
                inputs={"ids": "ZZZZZZZ"},
                assertions=[
                    "row_matches_empty_or_error_recorded",
                ],
            ),
            SemanticTest(
                name="isin_primary_provider_is_openfigi",
                description="Manifest pins openfigi as the primary so the rebuild cannot swap in a heuristic.",
                inputs={},
                assertions=[
                    "provider_chain_primary_equals_openfigi",
                ],
            ),
        ],
    )


__all__ = ["isin"]
