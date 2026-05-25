"""EQS — Equity screener.

Bloomberg ``EQS<GO>`` analogue. Operator filters a universe (SP500,
NDX, custom list) by a multi-criteria DSL (sector, market cap band,
P/E range, dividend yield, growth, beta, etc.) and returns the
matching tickers with their evaluated metrics. Backend handler is
``engine/functions/screening/eqs.py`` which fans out to yfinance for
the live factor pulls and respects a row-limit cap.
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
def eqs() -> FunctionManifest:
    return FunctionManifest(
        code="EQS",
        name="Equity Screener",
        category=Category.SCREENING,
        intent=(
            "Filter a chosen equity universe by sector, market cap, P/E, dividend yield, growth, beta "
            "and other fundamentals via a DSL query, returning the matching tickers with their "
            "evaluated metrics and one-click DES/GP drill-downs."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="query",
                label="DSL query",
                control=ControlKind.TEXT,
                required=True,
                description='Filter expression e.g. \'sector = "Technology" AND marketCap > 50000000000\'.',
            ),
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.SELECT,
                required=True,
                description="Named universe or free-form ticker list.",
                options=["SP500", "NDX", "DJIA", "RUSSELL2000", "CUSTOM"],
            ),
            InputSpec(
                name="saved_screen",
                label="Saved screen",
                control=ControlKind.SELECT,
                required=False,
                description="Load a previously saved filter preset.",
                options=["TECH-LG", "VAL-LBT", "US-MEGA", "DIV-Y"],
            ),
            InputSpec(
                name="limit",
                label="Row limit",
                control=ControlKind.SELECT,
                required=True,
                description="Cap on matched-row results returned.",
                options=[25, 50, 100, 250, 500],
            ),
            InputSpec(
                name="sort_by",
                label="Sort",
                control=ControlKind.SELECT,
                required=False,
                description="Sort key for the result table.",
                options=["matched_score", "market_cap_desc", "pe_asc", "div_yield_desc", "change_pct_desc"],
            ),
            InputSpec(
                name="live_screen",
                label="Live data",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Force a live yfinance refresh rather than the cached template path.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; provider may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "query": 'sector = "Technology" AND marketCap > 50000000000',
            "universe": "SP500",
            "limit": 50,
            "sort_by": "market_cap_desc",
            "live_screen": True,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["openfigi", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "matched", "scanned", "data_mode"],
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
                ColumnSpec(key="sector", label="Sector", kind="tag"),
                ColumnSpec(key="market_cap", label="Mkt Cap", kind="currency", format="si"),
                ColumnSpec(key="pe", label="P/E", kind="number", format="%.2f"),
                ColumnSpec(key="dividend_yield", label="Div Y", kind="percent", format="%.2f"),
                ColumnSpec(key="beta", label="β", kind="number", format="%.2f"),
                ColumnSpec(key="change_pct", label="Δ %", kind="percent", format="%.2f"),
                ColumnSpec(key="volume", label="Vol", kind="number", format="si"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matched", label="Matched", kind="kpi"),
                CardSlot(key="scanned", label="Scanned", kind="kpi"),
                CardSlot(key="median_change_pct", label="Median Δ", kind="trend_pill", unit="%"),
                CardSlot(key="top_sector", label="Top Sector", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "EQS parses the DSL query into a small AST (sector =, marketCap >, pe <, dividendYield >, "
            "beta <, country =, growth >, returnOnEquity >, etc.) then resolves the universe — named "
            "universes load constituent ticker lists from bundled JSON (sp500.json, ndx.json) and "
            "free-form lists are split on whitespace/commas. For each ticker the live_screen=True path "
            "fans out to yfinance, pulls the canonical info dict, and evaluates every predicate; "
            "rows where any required field is missing are dropped with a warning rather than being "
            "treated as a soft pass. Matches are scored by the predicate weight and sorted by sort_by. "
            "Saved screens are presets that just preload (query, universe, sort_by). Results are "
            "capped at limit. Next actions: save_screen, export_csv, open_in_GP for any selected row."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Canonical ticker symbol.", source="universe"),
            "rows[].name": FieldDef(description="Long company name.", source="yfinance"),
            "rows[].sector": FieldDef(description="GICS-style sector classification.", source="yfinance"),
            "rows[].market_cap": FieldDef(unit="USD", description="Market capitalization in USD.", source="yfinance"),
            "rows[].pe": FieldDef(description="Trailing price/earnings.", source="yfinance"),
            "rows[].dividend_yield": FieldDef(unit="ratio", description="Trailing dividend yield as a decimal.", source="yfinance"),
            "rows[].beta": FieldDef(description="5Y monthly beta vs benchmark.", source="yfinance"),
            "rows[].change_pct": FieldDef(unit="%", description="Daily change in percent.", source="yfinance"),
            "rows[].volume": FieldDef(unit="shares", description="Session volume.", source="yfinance"),
            "matched": FieldDef(unit="count", description="Number of rows passing every predicate.", source="screener"),
            "scanned": FieldDef(unit="count", description="Total universe size scanned.", source="screener"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="eqs_matched_subset_of_scanned",
                description="matched is always <= scanned and every row passes the query predicate.",
                inputs={"query": 'sector = "Technology" AND marketCap > 50000000000', "universe": "SP500"},
                assertions=[
                    "matched_le_scanned",
                    "every_row_passes_predicate",
                ],
            ),
            SemanticTest(
                name="eqs_live_screen_true_avoids_template_fallback",
                description="With live_screen=True the result is sourced from yfinance, not the 5-row template stub.",
                inputs={"live_screen": True, "universe": "SP500"},
                assertions=[
                    "source_includes_yfinance",
                    "result_row_count_exceeds_template_stub",
                ],
            ),
            SemanticTest(
                name="eqs_saved_screen_loads_predefined_query",
                description="Selecting a saved_screen populates query and universe consistently.",
                inputs={"saved_screen": "TECH-LG"},
                assertions=[
                    "query_matches_saved_screen",
                    "universe_matches_saved_screen",
                ],
            ),
            SemanticTest(
                name="eqs_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="eqs_provider_unavailable_returns_empty_rows_not_synthetic",
                description="When yfinance is unreachable, rows=[] and data_mode=provider_unavailable with no fabricated rows.",
                inputs={},
                assertions=[
                    "rows_is_empty_array_on_provider_failure",
                    "data_mode_equals_provider_unavailable",
                    "no_synthetic_fields",
                ],
            ),
        ],
    )


__all__ = ["eqs"]
