"""SRCH — Global symbol search.

Quick global symbol palette. SECF is the structured cross-asset filter
with confidence + asset-class controls; SRCH is the lightweight
typeahead-style global palette every pane wires to (command-K). Routes
to OpenFIGI for canonical figi/exchange resolution with a local cache
so a second keystroke returns instantly.
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
def srch() -> FunctionManifest:
    return FunctionManifest(
        code="SRCH",
        name="Global Symbol Search",
        category=Category.SCREENING,
        intent=(
            "Provide an instant typeahead global symbol palette (command-K) that resolves any "
            "fragment to canonical instruments across every asset class, cached locally so a second "
            "keystroke returns under 10 ms."
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
                description="Free-text fragment routed to OpenFIGI name + ticker search.",
            ),
            InputSpec(
                name="limit",
                label="Row limit",
                control=ControlKind.SELECT,
                required=True,
                description="Cap on returned matches; keep small for typeahead responsiveness.",
                options=[5, 10, 20, 50],
            ),
            InputSpec(
                name="prefer_recent",
                label="Prefer recent",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Boost rows that match the operator's recent-symbol history.",
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
            "limit": 10,
            "prefer_recent": True,
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
            must_have=["as_of", "query", "rows", "data_mode"],
            rows=True,
            series=False,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="asset_class", label="Class", kind="tag"),
                ColumnSpec(key="exchange", label="Ex.", kind="tag"),
                ColumnSpec(key="figi", label="FIGI", kind="text"),
                ColumnSpec(key="recent", label="Recent", kind="tag"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matched", label="Matched", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "SRCH is the lightweight cousin of SECF tuned for command-K typeahead. The query goes "
            "through three tiers in order: (1) DuckDB recent-symbols cache when prefer_recent=True "
            "for under-millisecond hits, (2) bundled SP500/NDX/Binance ticker tables for offline "
            "completion, (3) OpenFIGI online lookup as the canonical source. Hits from the OpenFIGI "
            "tier are persisted into DuckDB so subsequent keystrokes never refetch. The output is "
            "intentionally cardless — the palette renders rows directly and the operator hits Enter "
            "to navigate. Next actions: open_in_des, add_to_watch."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Canonical ticker symbol.", source="openfigi"),
            "rows[].name": FieldDef(description="Issuer / instrument name.", source="openfigi"),
            "rows[].asset_class": FieldDef(description="Mapped asset class tag.", source="derived"),
            "rows[].exchange": FieldDef(description="Primary exchange MIC.", source="openfigi"),
            "rows[].figi": FieldDef(description="OpenFIGI composite figi.", source="openfigi"),
            "rows[].recent": FieldDef(description="True when the row came from the recent-symbols cache.", source="store"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="srch_prefix_match_returns_canonical_ticker_first",
                description="Query 'AAP' returns AAPL as the top row when AAPL is in the universe.",
                inputs={"query": "AAP"},
                assertions=["top_row_symbol_starts_with_aap"],
            ),
            SemanticTest(
                name="srch_recent_cache_short_circuits_when_prefer_recent_true",
                description="With prefer_recent=True a previously-seen symbol surfaces from cache with recent=True.",
                inputs={"query": "AAPL", "prefer_recent": True},
                assertions=[
                    "any_row_recent_equals_true",
                    "top_row_symbol_equals_aapl",
                ],
            ),
            SemanticTest(
                name="srch_limit_caps_returned_rows",
                description="With limit=5 the result row count is <= 5.",
                inputs={"query": "a", "limit": 5},
                assertions=["row_count_at_most_5"],
            ),
            SemanticTest(
                name="srch_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="srch_provider_unavailable_returns_empty_rows_not_synthetic",
                description="When OpenFIGI is unreachable rows=[] (or just cache hits) and data_mode reflects degradation.",
                inputs={},
                assertions=[
                    "rows_from_cache_only_when_openfigi_unavailable",
                    "data_mode_equals_cached_snapshot_or_provider_unavailable",
                    "no_synthetic_fields",
                ],
            ),
        ],
    )


__all__ = ["srch"]
