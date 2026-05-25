"""EMSX — Execution Management trade ticket.

Two-mode order ticket: preview (submit=False, paper) by default; live
submit only when the user explicitly arms the confirm checkbox and the
``paper_mode`` input is False. Safe-by-default: ``paper_mode=True`` is a
required boolean input so the rebuild contract cannot ship a ticket that
silently fires a live order.
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
def emsx() -> FunctionManifest:
    return FunctionManifest(
        code="EMSX",
        name="Execution Management",
        category=Category.TRADE_EXECUTION,
        intent=(
            "Compose, preview, and (only when explicitly armed) submit a trade ticket through "
            "the asset-class-appropriate broker adapter — paper preview by default, live only "
            "after explicit confirmation."
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
                description="Instrument to trade; broker is auto-selected by asset class.",
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
                description="Order size in base units; must be > 0 to preview or submit.",
                min=0.0,
                step=0.001,
            ),
            InputSpec(
                name="order_type",
                label="Type",
                control=ControlKind.SELECT,
                required=True,
                description="MARKET = take liquidity; LIMIT = post a price.",
                options=["MARKET", "LIMIT"],
            ),
            InputSpec(
                name="tif",
                label="TIF",
                control=ControlKind.SELECT,
                required=True,
                description="Time-in-force directive forwarded to the broker.",
                options=["DAY", "GTC", "IOC", "FOK"],
            ),
            InputSpec(
                name="price",
                label="Limit price",
                control=ControlKind.NUMBER,
                required=False,
                description="Required when order_type=LIMIT; ignored otherwise.",
                min=0.0,
                step=0.0001,
                depends_on=["order_type"],
            ),
            InputSpec(
                name="leverage",
                label="Leverage",
                control=ControlKind.NUMBER,
                required=False,
                description="Optional leverage hint forwarded to leveraged-venue brokers.",
                min=1.0,
                max=125.0,
                step=1.0,
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description=(
                    "Safe-by-default. True forces preview-only round-trip with no broker mutation. "
                    "Must be explicitly set False before any submit=True call can reach a venue."
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
                CardSlot(key="order_id", label="Order ID", kind="badge"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "EMSX is the canonical multi-asset trade ticket. Preview path (submit=False or "
            "paper_mode=True) returns a faithful round-trip echo of side/quantity/type/tif/price/leverage "
            "without touching the broker. The live submit path is only reachable when (a) the user "
            "supplies submit=True, (b) paper_mode=False, and (c) the asset class has a broker adapter "
            "wired. The router selects the broker per asset_class (crypto → binance_broker, equity/ETF → "
            "alpaca_broker, FX → oanda_broker, bond/commodity/derivative → ibkr_broker). Filled live "
            "orders write to the local order_history audit table; an audit-write failure surfaces "
            "instead of being swallowed. Missing broker for the asset class returns "
            "status=provider_unavailable rather than a silent no-op."
        ),
        formula_dict={
            "Notional": Formula(
                expression=r"notional = quantity \times (price\_or\_last)",
                variables={"price_or_last": "limit price when order_type=LIMIT else current quote"},
            ),
        },
        field_dict={
            "status": FieldDef(description="preview / filled / input_required / provider_unavailable.", source="emsx"),
            "broker": FieldDef(description="Adapter that handled the ticket; 'paper' for preview.", source="emsx"),
            "submit": FieldDef(description="Echo of the submit flag actually used.", source="emsx"),
            "side": FieldDef(description="BUY or SELL.", source="emsx"),
            "quantity": FieldDef(unit="base", description="Order size in base units.", source="emsx"),
            "order_type": FieldDef(description="MARKET or LIMIT.", source="emsx"),
            "tif": FieldDef(description="DAY, GTC, IOC, FOK.", source="emsx"),
            "price": FieldDef(unit="quote", description="Limit price echoed back; null on MARKET.", source="emsx"),
            "leverage": FieldDef(unit="x", description="Leverage hint forwarded to broker if supported.", source="emsx"),
            "order_id": FieldDef(description="Broker-assigned order id on live fill.", source="broker"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["order_filled", "order_rejected", "order_cancelled"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="emsx_default_paper_mode_blocks_live_submit",
                description="paper_mode=True (the default) returns status=preview with broker='paper' regardless of submit flag.",
                inputs={"symbol": "AAPL", "side": "BUY", "quantity": 10, "paper_mode": True, "submit": True},
                assertions=[
                    "status == 'preview'",
                    "broker == 'paper'",
                    "no_broker_mutating_call_made",
                ],
            ),
            SemanticTest(
                name="emsx_preview_echoes_inputs",
                description="Preview returns the side/quantity/type/tif/price/leverage the caller passed in.",
                inputs={"symbol": "AAPL", "side": "SELL", "quantity": 5, "order_type": "LIMIT", "price": 200.5},
                assertions=[
                    "side == 'SELL'",
                    "quantity == 5",
                    "order_type == 'LIMIT'",
                    "price == 200.5",
                ],
            ),
            SemanticTest(
                name="emsx_zero_quantity_input_required",
                description="quantity<=0 returns status=input_required with an actionable reason.",
                inputs={"symbol": "AAPL", "quantity": 0},
                assertions=[
                    "status == 'input_required'",
                    "reason_mentions_quantity",
                ],
            ),
            SemanticTest(
                name="emsx_no_broker_for_asset_class_unavailable",
                description="Live submit without a broker for the asset class returns status=provider_unavailable.",
                inputs={"symbol": "AAPL", "paper_mode": False, "submit": True},
                assertions=[
                    "status == 'provider_unavailable'",
                    "data_mode in {'not_configured', 'provider_unavailable'}",
                ],
            ),
        ],
    )


__all__ = ["emsx"]
