"""MOST — Most active multi-asset top movers.

Bloomberg ``MOST<GO>`` analogue. Top-50 (or N) movers by volume / |%Δ|
/ dollar volume across equities, crypto, and FX. Visualized as a
ranked horizontal bar ladder so the operator sees who's leading. Per-
asset-class tabs route equity to yfinance, crypto to binance, fx to
yfinance USD pairs.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
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
def most() -> FunctionManifest:
    return FunctionManifest(
        code="MOST",
        name="Top Movers",
        category=Category.SCREENING,
        intent=(
            "Surface the top-N movers across equities, crypto, and FX by volume, |%Δ|, or dollar "
            "volume, ranked as a horizontal bar ladder so the operator reads leadership at a glance."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.CRYPTO, AssetClass.FX, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="asset_class",
                label="Asset class",
                control=ControlKind.SELECT,
                required=True,
                description="Tab/filter for one asset class.",
                options=["all", "equities", "crypto", "fx", "etf"],
            ),
            InputSpec(
                name="sort",
                label="Sort",
                control=ControlKind.SELECT,
                required=True,
                description="Activity metric driving the rank.",
                options=["volume", "abs_change", "dollar_volume", "trades_count"],
            ),
            InputSpec(
                name="limit",
                label="Top N",
                control=ControlKind.SELECT,
                required=True,
                description="Cap on returned rows.",
                options=[10, 25, 50, 100],
            ),
            InputSpec(
                name="live_screen",
                label="Live data",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Force a live refresh rather than the cached template path.",
            ),
            InputSpec(
                name="saved_screen",
                label="Saved screen",
                control=ControlKind.SELECT,
                required=False,
                description="Load a previously saved movers preset.",
                options=["EQ-VOL", "EQ-DLR", "CR-MOV", "FX-MOV"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; provider may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "asset_class": "all",
            "sort": "volume",
            "limit": 50,
            "live_screen": True,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "asset_class_filter", "sort", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="", label="Activity"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="asset_class", label="Class", kind="tag"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.4f"),
                ColumnSpec(key="change_pct", label="Δ %", kind="percent", format="%.2f"),
                ColumnSpec(key="volume", label="Vol", kind="number", format="si"),
                ColumnSpec(key="dollar_volume", label="$ Vol", kind="currency", format="si"),
                ColumnSpec(key="activity_score", label="Score", kind="number", format="%.2f"),
                ColumnSpec(key="quote_state", label="State", kind="tag"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matched", label="Returned", kind="kpi"),
                CardSlot(key="live_count", label="Live", kind="kpi"),
                CardSlot(key="median_abs_change_pct", label="Median |Δ|", kind="trend_pill", unit="%"),
                CardSlot(key="top_mover", label="Top Mover", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MOST aggregates per-asset-class candidate pools. Equities/ETFs come from a curated "
            "active-symbol list (SP500 + Russell-2000 active subset) plus the yfinance ``trending`` "
            "tape; crypto from the Binance USDT ticker list; FX from the yfinance 6E/6J/6B/6A pair "
            "list. Each candidate gets a quote (last, change_pct, volume, dollar_volume) via the "
            "asset-class-appropriate adapter (binance for crypto, yfinance for the rest) and an "
            "activity_score = z(volume) + z(|change_pct|) + z(dollar_volume) for cross-asset rank. "
            "Rows are sorted by the chosen `sort` metric desc and capped at `limit`. asset_class=all "
            "interleaves classes by activity_score. live_screen=False short-circuits to a small "
            "cached sample to keep the pane responsive during outages — rows are tagged "
            "quote_state=cached. Next actions: save_screen, export_csv, open_in_gp."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Canonical ticker / pair.", source="universe"),
            "rows[].name": FieldDef(description="Issuer / instrument name.", source="provider"),
            "rows[].asset_class": FieldDef(description="equities / crypto / fx / etf.", source="derived"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Last trade price.", source="provider"),
            "rows[].change_pct": FieldDef(unit="%", description="Daily change in percent.", source="provider"),
            "rows[].volume": FieldDef(unit="units", description="Session volume in shares or coins.", source="provider"),
            "rows[].dollar_volume": FieldDef(unit="USD", description="last * volume (USD where conversion known).", source="computed"),
            "rows[].activity_score": FieldDef(description="Cross-asset z-score blend.", source="computed"),
            "rows[].quote_state": FieldDef(description="live / cached / stale.", source="envelope"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="most_chart_grammar_is_bar_ladder",
                description="MOST manifest pins chart_grammar.kind to bar_ladder (ranked horizontal bars by activity).",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'bar_ladder'"],
            ),
            SemanticTest(
                name="most_asset_class_crypto_routes_to_binance",
                description="With asset_class=crypto every row's source resolves to binance.",
                inputs={"asset_class": "crypto"},
                assertions=[
                    "all_rows_source_equals_binance",
                    "all_rows_asset_class_equals_crypto",
                ],
            ),
            SemanticTest(
                name="most_sort_volume_descending",
                description="With sort=volume rows are monotonically non-increasing in volume.",
                inputs={"sort": "volume"},
                assertions=["rows_monotonically_non_increasing_in_volume"],
            ),
            SemanticTest(
                name="most_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="most_live_screen_false_marks_rows_cached_not_live",
                description="With live_screen=False every returned row carries quote_state=cached.",
                inputs={"live_screen": False},
                assertions=["all_rows_quote_state_equals_cached"],
            ),
        ],
    )


__all__ = ["most"]
