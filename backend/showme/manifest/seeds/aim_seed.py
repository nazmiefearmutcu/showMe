"""AIM — Order Management (open + filled across brokers).

Cross-broker order ledger: surfaces every open order from each configured
broker plus a persisted tail of historical orders from the local
``order_history`` store. Read-only — submission lives in EMSX/BBGT/FXGO/TSOX.
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
def aim() -> FunctionManifest:
    return FunctionManifest(
        code="AIM",
        name="Order Management",
        category=Category.TRADE_EXECUTION,
        intent=(
            "Show every open broker order plus a persisted tail of recent order history "
            "across all configured brokers in a single read-only ledger."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.BOND,
            AssetClass.FUTURE,
            AssetClass.OPTION,
        ],
        inputs=[
            InputSpec(
                name="broker_filter",
                label="Brokers",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to specific broker adapters; empty = all configured.",
                options=["binance_broker", "alpaca_broker", "ibkr_broker", "oanda_broker"],
            ),
            InputSpec(
                name="status_filter",
                label="Status",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter rows by order status (open / filled / cancelled).",
                options=["open", "filled", "partially_filled", "cancelled", "rejected"],
            ),
            InputSpec(
                name="limit",
                label="History tail",
                control=ControlKind.NUMBER,
                required=False,
                description="How many historical orders to include from the local store.",
                min=1,
                max=1000,
                step=10,
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description=(
                    "Safe-by-default. AIM is read-only by design — this flag is exposed for "
                    "consistency with the order-ticket family so a downstream caller cannot "
                    "wire AIM into a state-changing flow without explicitly clearing it."
                ),
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "broker_filter": [],
            "status_filter": [],
            "limit": 200,
            "paper_mode": True,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            # AIM fans out across binance/alpaca/ibkr/oanda broker adapters and
            # degrades to the persisted order_history cached snapshot — it is NOT
            # a single ccxt_broker provider, so name it for the multi-broker fanout.
            primary="broker_adapters",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=10, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "orders", "brokers_checked", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="created_at", label="Created", kind="datetime", format="yyyy-MM-dd HH:mm:ss"),
                ColumnSpec(key="broker", label="Broker", kind="tag"),
                ColumnSpec(key="order_id", label="Order ID", kind="text"),
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="side", label="Side", kind="tag"),
                ColumnSpec(key="quantity", label="Qty", kind="number", format="%.6g"),
                ColumnSpec(key="price", label="Price", kind="currency", unit="quote", format="%.4f"),
                ColumnSpec(key="type", label="Type", kind="tag"),
                ColumnSpec(key="tif", label="TIF", kind="tag"),
                ColumnSpec(key="status", label="Status", kind="tag"),
                ColumnSpec(key="filled_qty", label="Filled", kind="number", format="%.6g"),
                ColumnSpec(key="avg_fill_px", label="Avg Fill", kind="currency", unit="quote", format="%.4f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="open_count", label="Open", kind="kpi"),
                # Counts ALL filled/partially-filled rows in the history tail,
                # not just today's — label honestly as "Filled" (the data key
                # `filled_today` is kept for contract stability).
                CardSlot(key="filled_today", label="Filled", kind="kpi"),
                CardSlot(key="brokers_online", label="Brokers", kind="kpi"),
                CardSlot(key="total_notional", label="Notional", kind="kpi", unit="USD"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "AIM iterates over every configured broker adapter (binance/alpaca/ibkr/oanda), calling "
            "get_open_orders() in parallel and collecting per-broker results. Provider failures are "
            "recorded as warnings without dropping rows from working brokers. The persisted local "
            "order_history store contributes a configurable tail of recent orders so the user sees a "
            "cross-broker chronological ledger even when individual brokers are momentarily down. "
            "AIM never mutates state — it is the read-only counterpart to EMSX/BBGT/FXGO/TSOX."
        ),
        field_dict={
            "orders[].broker": FieldDef(description="Adapter name (binance_broker, alpaca_broker, ...).", source="broker"),
            "orders[].order_id": FieldDef(description="Broker-assigned order identifier.", source="broker"),
            "orders[].symbol": FieldDef(description="Canonical instrument symbol.", source="broker"),
            "orders[].side": FieldDef(description="BUY or SELL.", source="broker"),
            "orders[].quantity": FieldDef(unit="base", description="Order size in base units.", source="broker"),
            "orders[].price": FieldDef(unit="quote", description="Limit price; null for market orders.", source="broker"),
            "orders[].status": FieldDef(description="open / filled / partially_filled / cancelled / rejected.", source="broker"),
            "orders[].filled_qty": FieldDef(unit="base", description="Quantity executed so far.", source="broker"),
            "orders[].avg_fill_px": FieldDef(unit="quote", description="Volume-weighted average fill price.", source="broker"),
            "brokers_checked": FieldDef(description="List of broker adapters AIM polled this refresh.", source="aim"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["new_fill", "order_rejected", "order_cancelled_externally"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="aim_no_brokers_returns_empty_with_warning",
                description="With no broker adapters configured, AIM returns orders=[] and an actionable warning.",
                inputs={},
                assertions=[
                    "orders == []",
                    "data_mode == 'not_configured'",
                    "warnings_non_empty",
                ],
            ),
            SemanticTest(
                name="aim_per_broker_failure_does_not_drop_others",
                description="If one broker raises, other brokers' rows still appear and provider_errors logs the failure.",
                inputs={},
                assertions=[
                    "rows_from_working_brokers_present",
                    "provider_errors_lists_failing_broker",
                ],
            ),
            SemanticTest(
                name="aim_history_tail_respects_limit",
                description="limit=50 yields at most 50 rows from order_history regardless of total persisted rows.",
                inputs={"limit": 50},
                assertions=["history_rows_length_at_most_50"],
            ),
            SemanticTest(
                name="aim_read_only_no_state_mutation",
                description="Polling AIM does not submit, cancel, or modify any order — it is pure read.",
                inputs={},
                assertions=["no_broker_mutating_call_made"],
            ),
        ],
    )


__all__ = ["aim"]
