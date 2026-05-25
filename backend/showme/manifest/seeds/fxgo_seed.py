"""FXGO — FX trading desk.

Specialised FX ticket. Shares the EMSX two-mode safe-by-default contract
(paper_mode=True default; live submit gated on explicit arming) but
constrains the default symbol presentation and asset_class hint to FX
pairs and routes through the oanda broker by preference.
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
def fxgo() -> FunctionManifest:
    return FunctionManifest(
        code="FXGO",
        name="FX Trading",
        category=Category.TRADE_EXECUTION,
        intent=(
            "Compose, preview, and (only after explicit arming) submit an FX spot/forward ticket "
            "through the FX broker — paper preview by default, no live call without consent."
        ),
        asset_classes=[AssetClass.FX],
        inputs=[
            InputSpec(
                name="symbol",
                label="Pair",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="FX pair (EURUSD, GBPUSD, USDJPY, ...).",
            ),
            InputSpec(
                name="side",
                label="Side",
                control=ControlKind.SELECT,
                required=True,
                description="BUY base / SELL base.",
                options=["BUY", "SELL"],
            ),
            InputSpec(
                name="quantity",
                label="Notional",
                control=ControlKind.NUMBER,
                required=True,
                description="Order size in base currency units (FX notionals can be lot-sized).",
                min=0.0,
                step=1000.0,
            ),
            InputSpec(
                name="order_type",
                label="Type",
                control=ControlKind.SELECT,
                required=True,
                description="MARKET takes the venue spread; LIMIT posts a price.",
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
                description="Quote-currency price per base unit; required when order_type=LIMIT.",
                min=0.0,
                step=0.00001,
                depends_on=["order_type"],
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description=(
                    "Safe-by-default. True forces paper preview round-trip; flip to False plus "
                    "confirm arm before any live FX submit can reach the venue."
                ),
            ),
        ],
        defaults={
            "symbol": "EURUSD",
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
                CardSlot(key="quantity", label="Notional", kind="big_number"),
                CardSlot(key="order_type", label="Type", kind="badge"),
                CardSlot(key="tif", label="TIF", kind="badge"),
                CardSlot(key="price", label="Price", kind="kpi", unit="quote"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FXGO is the FX specialisation of the EMSX trade-ticket engine. Asset class is pinned to "
            "FX so the broker router picks oanda_broker first (fallback ibkr_broker). Quantity is "
            "treated as base-currency notional; LIMIT price is quote per base. The two-mode safety "
            "contract is inherited: preview path returns a faithful round-trip without any broker "
            "call; live submit fires only when paper_mode=False, submit=True, and a broker is wired. "
            "Without an FX broker, FXGO returns status=provider_unavailable with an actionable next-action."
        ),
        formula_dict={
            "QuoteNotional": Formula(
                expression=r"quote\_notional = base\_quantity \times price",
                variables={"base_quantity": "Order size in base ccy", "price": "Quote per base"},
            ),
        },
        field_dict={
            "status": FieldDef(description="preview / filled / input_required / provider_unavailable.", source="fxgo"),
            "broker": FieldDef(description="FX broker used; 'paper' on preview.", source="fxgo"),
            "side": FieldDef(description="BUY base / SELL base.", source="fxgo"),
            "quantity": FieldDef(unit="base_ccy", description="Notional in base currency.", source="fxgo"),
            "order_type": FieldDef(description="MARKET or LIMIT.", source="fxgo"),
            "tif": FieldDef(description="DAY/GTC/IOC/FOK.", source="fxgo"),
            "price": FieldDef(unit="quote_ccy", description="Quote per base; null on MARKET.", source="fxgo"),
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
                name="fxgo_default_paper_mode_blocks_live",
                description="paper_mode=True default keeps FXGO previewing, even with submit=True.",
                inputs={"symbol": "EURUSD", "quantity": 100000, "paper_mode": True, "submit": True},
                assertions=[
                    "status == 'preview'",
                    "broker == 'paper'",
                    "no_broker_mutating_call_made",
                ],
            ),
            SemanticTest(
                name="fxgo_preview_returns_notional",
                description="FX preview echoes the FX notional exactly as submitted.",
                inputs={"symbol": "GBPUSD", "side": "SELL", "quantity": 250000, "order_type": "LIMIT", "price": 1.2755},
                assertions=[
                    "side == 'SELL'",
                    "quantity == 250000",
                    "price == 1.2755",
                ],
            ),
            SemanticTest(
                name="fxgo_no_fx_broker_returns_unavailable",
                description="Live submit without an FX broker returns status=provider_unavailable.",
                inputs={"symbol": "USDJPY", "quantity": 100000, "paper_mode": False, "submit": True},
                assertions=[
                    "status == 'provider_unavailable'",
                    "data_mode in {'not_configured', 'provider_unavailable'}",
                ],
            ),
        ],
    )


__all__ = ["fxgo"]
