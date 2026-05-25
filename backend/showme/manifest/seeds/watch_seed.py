"""WATCH — Operator-grade watchlist.

Persistent multi-list watchlist with live quotes + sparklines + per-row
alert counts. The DuckDB-backed store (watch_lists / watch_items) is the
canonical "selected symbol" context other panes subscribe to via
``useWatchStore``.
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
    AlertingSpec,
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
def watch() -> FunctionManifest:
    return FunctionManifest(
        code="WATCH",
        name="Watchlist",
        category=Category.SCREENING,
        intent=(
            "A first-class global watchlist that holds named instruments across all asset classes, "
            "shows live quotes + sparklines + alerts, and is the canonical context other panes subscribe to."
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
                name="list_id",
                label="List",
                control=ControlKind.SELECT,
                required=True,
                description="Active watchlist; multiple named lists supported.",
            ),
            InputSpec(
                name="sort_by",
                label="Sort",
                control=ControlKind.SELECT,
                required=True,
                description="Row ordering.",
                options=[
                    "manual",
                    "day_change_pct_desc",
                    "day_change_pct_asc",
                    "last_price_asc",
                    "last_price_desc",
                    "volume_desc",
                    "alpha",
                ],
            ),
            InputSpec(
                name="show_sparklines",
                label="Sparklines",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Render an inline sparkline per row.",
            ),
            InputSpec(
                name="sparkline_window",
                label="Spark window",
                control=ControlKind.SELECT,
                required=False,
                description="Time window covered by the per-row sparkline.",
                options=["1D", "5D", "1M"],
                depends_on=["show_sparklines"],
            ),
            InputSpec(
                name="show_alerts",
                label="Show alert chips",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Show the alert-count chip per row.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; per-row chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "list_id": "default",
            "sort_by": "manual",
            "show_sparklines": True,
            "sparkline_window": "1D",
            "show_alerts": True,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        # WATCH fans out per-symbol via POST /api/watch/quote-bulk: crypto rows
        # take binance, equity/ETF/etc. take yfinance, with a snapshot
        # fallback. Primary picks yfinance for the route's median row mix.
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "list_id", "rows", "data_mode"],
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
                ColumnSpec(key="last", label="Last", kind="currency", format="%.2f"),
                ColumnSpec(key="change", label="Δ", kind="currency", format="%.2f"),
                ColumnSpec(key="change_pct", label="Δ%", kind="percent", format="%.2f"),
                ColumnSpec(key="spark", label="Spark", kind="tag"),
                ColumnSpec(key="volume", label="Vol", kind="number", format="si"),
                ColumnSpec(key="asset_class", label="Class", kind="tag"),
                ColumnSpec(key="alert_count", label="Alerts", kind="number", format="%d"),
                ColumnSpec(key="as_of", label="As of", kind="datetime", format="rel"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="list_size", label="Symbols", kind="kpi"),
                CardSlot(key="advancers", label="Up", kind="kpi"),
                CardSlot(key="decliners", label="Down", kind="kpi"),
                CardSlot(key="unchanged", label="Flat", kind="kpi"),
                CardSlot(key="top_mover", label="Top Mover", kind="trend_pill", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "WATCH is backed by a persistent store in DuckDB (watch_lists + watch_items). The frontend "
            "useWatchStore reflects this state and is mounted globally so other panes can subscribe to "
            "the selected symbol or list contents. On render the pane sends the current list to "
            "POST /api/watch/quote-bulk; the backend buckets symbols by inferred asset_class, fans out "
            "per-adapter with a concurrency cap (default 8), and returns one row per symbol. Rows where "
            "the adapter fails carry an ``error`` field — UI shows an error chip instead of a synthetic "
            "green/red quote. Drag-reorder is immediate in the store and persisted on the next interval. "
            "Alerts are owned by ALRT; WATCH only displays count + chip indicator."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Canonical symbol.", source="store"),
            "rows[].name": FieldDef(description="Display name (OpenFIGI-resolved on first add).", source="openfigi"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Last trade price.", source="adapter"),
            "rows[].prev_close": FieldDef(unit="quote_ccy", description="Previous close.", source="adapter"),
            "rows[].change": FieldDef(unit="quote_ccy", description="last - prev_close.", source="computed"),
            "rows[].change_pct": FieldDef(unit="%", description="change / prev_close * 100.", source="computed"),
            "rows[].volume": FieldDef(unit="shares_or_coins", description="Session volume.", source="adapter"),
            "rows[].sparkline": FieldDef(unit="quote_ccy[]", description="Intraday close array.", source="adapter_history"),
            "rows[].asset_class": FieldDef(description="Inferred or stored asset class tag.", source="inferred"),
            "rows[].alert_count": FieldDef(unit="count", description="Active alerts owned by ALRT.", source="alrt_store"),
            "rows[].error": FieldDef(description="Per-row error reason when adapter failed.", source="adapter"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["alert_count_changed"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="watch_empty_list_returns_empty_rows_not_error",
                description="Empty list returns rows=[] and list_size=0 with no error.",
                inputs={"list_id": "empty_test"},
                assertions=[
                    "rows_is_empty_array",
                    "list_size_equals_zero",
                    "no_top_level_error",
                ],
            ),
            SemanticTest(
                name="watch_per_row_error_does_not_fake_quote",
                description="A failing adapter row carries an error field instead of a synthetic last/change.",
                inputs={"list_id": "default", "symbols": ["ZZZZZZ"]},
                assertions=[
                    "row_has_error_field",
                    "row_has_no_last_field",
                    "row_has_no_change_field",
                ],
            ),
            SemanticTest(
                name="watch_crypto_routed_to_binance_equity_to_yfinance",
                description="Symbol routing buckets crypto to binance and equities to yfinance.",
                inputs={"list_id": "default", "symbols": ["BTCUSDT", "AAPL"]},
                assertions=[
                    "btcusdt_row_source_equals_binance",
                    "aapl_row_source_equals_yfinance",
                ],
            ),
            SemanticTest(
                name="watch_sparkline_length_matches_window",
                description="Sparkline array length is consistent with the configured window.",
                inputs={"list_id": "default", "sparkline_window": "5D", "symbols": ["AAPL"]},
                assertions=["sparkline_length_at_least_5_per_day"],
            ),
            SemanticTest(
                name="watch_sort_by_day_change_pct_desc_is_actually_sorted",
                description="With sort_by=day_change_pct_desc rows are monotonically decreasing in change_pct.",
                inputs={"list_id": "default", "sort_by": "day_change_pct_desc"},
                assertions=["rows_monotonically_decreasing_in_change_pct"],
            ),
            SemanticTest(
                name="watch_reorder_persists_across_reload",
                description="Manual drag-reorder is persisted in DuckDB and survives a reload.",
                inputs={"list_id": "default"},
                assertions=["manual_order_persisted_after_reload"],
            ),
        ],
    )


__all__ = ["watch"]
