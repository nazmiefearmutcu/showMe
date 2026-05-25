"""SECF — Security search/filter (cross-asset).

Free-text security lookup that resolves a query against OpenFIGI plus
local universe caches. Returns the best-match canonical identifiers
with name, asset class, exchange, and a confidence score so an
operator can resolve a fragment like 'apple' or 'AAPL' to its
underlying canonical ticker before pulling DES/GP/HP.
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
def secf() -> FunctionManifest:
    return FunctionManifest(
        code="SECF",
        name="Security Search",
        category=Category.SCREENING,
        intent=(
            "Resolve a free-text query (ticker, ISIN, CUSIP, company name fragment) to canonical "
            "security identifiers across all asset classes via OpenFIGI plus local universe caches, "
            "returning the best matches ranked by confidence and asset class."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.FUTURE,
            AssetClass.INDEX,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="query",
                label="Query",
                control=ControlKind.TEXT,
                required=True,
                description="Free-text search: ticker, ISIN, CUSIP, FIGI, or company name fragment.",
            ),
            InputSpec(
                name="asset_class_filter",
                label="Asset classes",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict results to selected asset classes.",
                options=[
                    AssetClass.EQUITY.value,
                    AssetClass.ETF.value,
                    AssetClass.CRYPTO.value,
                    AssetClass.FX.value,
                    AssetClass.COMMODITY.value,
                    AssetClass.FUTURE.value,
                    AssetClass.INDEX.value,
                    AssetClass.BOND.value,
                ],
            ),
            InputSpec(
                name="exchange_filter",
                label="Exchanges",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to selected exchange MICs (XNAS, XNYS, BATS, …).",
            ),
            InputSpec(
                name="min_confidence",
                label="Min confidence",
                control=ControlKind.NUMBER,
                required=False,
                description="Drop matches below this confidence floor [0..1].",
                min=0,
                max=1,
                step=0.05,
            ),
            InputSpec(
                name="limit",
                label="Row limit",
                control=ControlKind.SELECT,
                required=True,
                description="Cap on returned matches.",
                options=[10, 25, 50, 100],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "query": "",
            "asset_class_filter": [],
            "exchange_filter": [],
            "min_confidence": 0.4,
            "limit": 25,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="openfigi",
            fallbacks=["yfinance", "binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "query", "rows", "matched", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="asset_class", label="Class", kind="tag"),
                ColumnSpec(key="exchange", label="Exchange", kind="tag"),
                ColumnSpec(key="figi", label="FIGI", kind="text"),
                ColumnSpec(key="isin", label="ISIN", kind="text"),
                ColumnSpec(key="confidence", label="Conf.", kind="number", format="%.2f"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matched", label="Matched", kind="kpi"),
                CardSlot(key="top_match", label="Top match", kind="badge"),
                CardSlot(key="top_confidence", label="Top conf.", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "SECF treats the query as a multi-key lookup. ISIN / CUSIP / FIGI patterns short-circuit "
            "to the OpenFIGI direct-lookup endpoint and return a single high-confidence row when the "
            "key matches. Ticker-shaped queries (^[A-Z0-9.-]+$) are routed first to local universe "
            "caches (SP500/NDX/RUSSELL/Binance symbol lists) for instant resolution, then to OpenFIGI "
            "for the canonical figi + exchange. Free-text fragments hit OpenFIGI's name search and "
            "are re-ranked by a confidence score that combines string-similarity, exchange weight "
            "(primary listing wins), and asset-class boost from asset_class_filter. min_confidence "
            "trims the tail. Results are deduped by figi. Next actions: open_in_des, open_in_gp, "
            "add_to_watch for any selected row."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Canonical ticker symbol.", source="openfigi"),
            "rows[].name": FieldDef(description="Issuer / instrument name.", source="openfigi"),
            "rows[].asset_class": FieldDef(description="Mapped asset class tag.", source="derived"),
            "rows[].exchange": FieldDef(description="Primary listing exchange MIC.", source="openfigi"),
            "rows[].figi": FieldDef(description="OpenFIGI Composite or Share-class figi.", source="openfigi"),
            "rows[].isin": FieldDef(description="ISIN when available.", source="openfigi"),
            "rows[].confidence": FieldDef(unit="[0,1]", description="Match confidence score.", source="ranker"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="secf_isin_lookup_returns_single_high_confidence_row",
                description="A valid ISIN query (e.g. US0378331005 for AAPL) returns one row with confidence >= 0.95.",
                inputs={"query": "US0378331005"},
                assertions=[
                    "rows_length_equals_one",
                    "top_row_confidence_at_least_0_95",
                    "top_row_symbol_equals_aapl",
                ],
            ),
            SemanticTest(
                name="secf_min_confidence_floor_drops_weak_matches",
                description="Every returned row has confidence >= min_confidence.",
                inputs={"query": "apple", "min_confidence": 0.6},
                assertions=["all_rows_confidence_at_least_0_6"],
            ),
            SemanticTest(
                name="secf_asset_class_filter_restricts_rows",
                description="asset_class_filter=[crypto] yields only crypto rows.",
                inputs={"query": "btc", "asset_class_filter": ["crypto"]},
                assertions=["all_rows_asset_class_equals_crypto"],
            ),
            SemanticTest(
                name="secf_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="secf_provider_unavailable_returns_empty_rows_not_synthetic",
                description="When OpenFIGI is unreachable rows=[] and data_mode=provider_unavailable; no guessed tickers.",
                inputs={},
                assertions=[
                    "rows_is_empty_array_on_provider_failure",
                    "data_mode_equals_provider_unavailable",
                    "no_synthetic_fields",
                ],
            ),
        ],
    )


__all__ = ["secf"]
