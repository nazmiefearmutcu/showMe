"""BBGT — Bloomberg-style multi-asset trade ticket.

Inherits the EMSX two-mode contract (paper preview by default, explicit
arm + paper_mode=False before any live submit) but presents as the
generalist multi-asset entry surface.
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
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def bbgt() -> FunctionManifest:
    return FunctionManifest(
        code="BBGT",
        name="Multi-Asset Trade Ticket",
        category=Category.TRADE_EXECUTION,
        intent=(
            "Compose, preview, and (only when explicitly armed) submit a multi-asset trade ticket "
            "through the asset-class-appropriate broker; paper preview by default."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.FUTURE,
            AssetClass.OPTION,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Any tradable symbol routed by asset class.",
            ),
            InputSpec(
                name="side",
                label="Side",
                control=ControlKind.SELECT,
                required=True,
                description="BUY or SELL.",
                options=["BUY", "SELL"],
            ),
            InputSpec(
                name="quantity",
                label="Quantity",
                control=ControlKind.NUMBER,
                required=True,
                description="Order size in base units.",
                min=0.0,
                step=0.001,
            ),
            InputSpec(
                name="order_type",
                label="Type",
                control=ControlKind.SELECT,
                required=True,
                description="MARKET or LIMIT.",
                options=["MARKET", "LIMIT"],
            ),
            InputSpec(
                name="tif",
                label="TIF",
                control=ControlKind.SELECT,
                required=True,
                description="Time-in-force directive.",
                options=["DAY", "GTC", "IOC", "FOK"],
            ),
            InputSpec(
                name="price",
                label="Limit price",
                control=ControlKind.NUMBER,
                required=False,
                description="Required when order_type=LIMIT.",
                min=0.0,
                step=0.0001,
                depends_on=["order_type"],
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description=(
                    "Safe-by-default. True keeps the ticket in preview round-trip; live submission "
                    "requires explicit False plus the confirm gate."
                ),
            ),
        ],
        defaults={
            "side": "BUY",
            "order_type": "MARKET",
            "tif": "GTC",
            "paper_mode": True,
        },
        provider_chain=ProviderChain(
            primary="ccxt_broker",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["status", "broker", "symbol", "side", "quantity", "order_type", "tif"],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="status", label="Status", kind="badge"),
                CardSlot(key="broker", label="Broker", kind="mode_pill"),
                CardSlot(key="side", label="Side", kind="trend_pill"),
                CardSlot(key="quantity", label="Quantity", kind="big_number"),
                CardSlot(key="order_type", label="Type", kind="badge"),
                CardSlot(key="tif", label="TIF", kind="badge"),
                CardSlot(key="price", label="Price", kind="kpi", unit="quote"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BBGT shares the EMSX engine but presents as a generalist multi-asset desk: any symbol "
            "from any asset class routes through the same broker-selection table (crypto → binance, "
            "equity/ETF → alpaca, FX → oanda, bond/commodity/derivative → ibkr). Preview path mirrors "
            "the request without any broker call; live submit fires only when paper_mode=False AND "
            "submit=True AND a broker exists for the asset class. The ticket never auto-fires on mount."
        ),
        formula_dict={
            "Notional": Formula(
                expression=r"notional = quantity \times (price\_or\_last)",
                variables={"quantity": "Order size", "price_or_last": "LIMIT price else current quote"},
            ),
        },
        field_dict={
            "status": FieldDef(description="preview / filled / input_required / provider_unavailable.", source="bbgt"),
            "broker": FieldDef(description="Broker adapter used; 'paper' on preview.", source="bbgt"),
            "side": FieldDef(description="BUY or SELL.", source="bbgt"),
            "quantity": FieldDef(unit="base", description="Order size.", source="bbgt"),
            "order_type": FieldDef(description="MARKET or LIMIT.", source="bbgt"),
            "tif": FieldDef(description="DAY/GTC/IOC/FOK.", source="bbgt"),
            "price": FieldDef(unit="quote", description="Limit price; null on MARKET.", source="bbgt"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["order_filled", "order_rejected"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="bbgt_paper_mode_blocks_live_call",
                description="Default paper_mode=True keeps BBGT in preview no matter what submit flag is passed.",
                inputs={"symbol": "AAPL", "quantity": 1, "paper_mode": True, "submit": True},
                assertions=[
                    "status == 'preview'",
                    "broker == 'paper'",
                    "no_broker_mutating_call_made",
                ],
            ),
            SemanticTest(
                name="bbgt_round_trip_echoes_ticket",
                description="Preview returns the exact side/quantity/type/tif submitted.",
                inputs={"symbol": "MSFT", "side": "SELL", "quantity": 7, "order_type": "LIMIT", "price": 425.0},
                assertions=[
                    "side == 'SELL'",
                    "quantity == 7",
                    "order_type == 'LIMIT'",
                    "price == 425.0",
                ],
            ),
            SemanticTest(
                name="bbgt_zero_qty_input_required",
                description="Zero or negative quantity yields status=input_required with an actionable reason.",
                inputs={"symbol": "AAPL", "quantity": 0},
                assertions=["status == 'input_required'"],
            ),
        ],
    )


__all__ = ["bbgt"]
