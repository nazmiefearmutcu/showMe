"""TSOX — Treasury / Bond order ticket.

Specialised bond/treasury ticket. Inherits the EMSX two-mode safe-by-default
contract; constrains the asset class to bonds and routes via the multi-asset
broker that supports rate-product venues (typically ibkr).
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
def tsox() -> FunctionManifest:
    return FunctionManifest(
        code="TSOX",
        name="Treasury Order Entry",
        category=Category.TRADE_EXECUTION,
        intent=(
            "Compose and preview a treasury / bond order ticket; live submission is gated on "
            "paper_mode=False plus the explicit confirm arm — the pane defaults to preview-only."
        ),
        asset_classes=[AssetClass.BOND, AssetClass.RATE],
        inputs=[
            InputSpec(
                name="symbol",
                label="Bond / future",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Treasury future or cash-bond identifier (e.g. ZN=F for 10Y note future).",
            ),
            InputSpec(
                name="side",
                label="Side",
                control=ControlKind.SELECT,
                required=True,
                description="BUY (long duration) or SELL (short duration).",
                options=["BUY", "SELL"],
            ),
            InputSpec(
                name="quantity",
                label="Quantity",
                control=ControlKind.NUMBER,
                required=True,
                description="Number of contracts or face value units.",
                min=0.0,
                step=1.0,
            ),
            InputSpec(
                name="order_type",
                label="Type",
                control=ControlKind.SELECT,
                required=True,
                description="MARKET or LIMIT (limit is normal practice for rate products).",
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
                description="Price (32nds permitted via decimal form, e.g. 110.015625); required when order_type=LIMIT.",
                min=0.0,
                step=0.015625,
                depends_on=["order_type"],
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description=(
                    "Safe-by-default. True keeps the ticket in preview round-trip; only "
                    "False plus the explicit confirm checkbox unlocks live broker submission."
                ),
            ),
        ],
        defaults={
            "symbol": "ZN=F",
            "side": "BUY",
            "order_type": "LIMIT",
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
            "TSOX is the rate-products specialisation of the EMSX trade-ticket engine. Asset class "
            "is pinned to BOND so the broker router prefers a fixed-income-capable adapter (ibkr). "
            "Quantity represents contracts (for futures) or face-value units (for cash bonds). The "
            "two-mode safety contract is preserved: preview returns a faithful round-trip; live "
            "submit fires only when paper_mode=False, submit=True, and a broker exists. Treasury "
            "venues frequently quote in 32nds — TSOX accepts decimal-equivalent prices and forwards "
            "without conversion."
        ),
        formula_dict={
            "DV01": Formula(
                expression=r"DV01 \approx -duration \times price \times 0.0001",
                variables={"duration": "Modified duration of the bond/future basket", "price": "Clean price"},
                notes="Informational — TSOX preview does not compute DV01 server-side.",
            ),
        },
        field_dict={
            "status": FieldDef(description="preview / filled / input_required / provider_unavailable.", source="tsox"),
            "broker": FieldDef(description="Broker adapter used; 'paper' on preview.", source="tsox"),
            "side": FieldDef(description="BUY (long duration) / SELL (short duration).", source="tsox"),
            "quantity": FieldDef(unit="contracts_or_face", description="Contracts or face-value units.", source="tsox"),
            "order_type": FieldDef(description="MARKET or LIMIT (LIMIT preferred for rate products).", source="tsox"),
            "tif": FieldDef(description="DAY/GTC/IOC/FOK.", source="tsox"),
            "price": FieldDef(unit="price", description="Decimal-equivalent of 32nds; null on MARKET.", source="tsox"),
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
                name="tsox_paper_mode_blocks_live_submit",
                description="paper_mode=True (default) returns status=preview for any submit flag.",
                inputs={"symbol": "ZN=F", "side": "BUY", "quantity": 1, "paper_mode": True, "submit": True},
                assertions=[
                    "status == 'preview'",
                    "broker == 'paper'",
                    "no_broker_mutating_call_made",
                ],
            ),
            SemanticTest(
                name="tsox_preview_echoes_limit_price",
                description="Preview round-trips the user-supplied limit price (e.g. 110.015625 = 110-0.5/32).",
                inputs={"symbol": "ZN=F", "order_type": "LIMIT", "price": 110.015625, "quantity": 1},
                assertions=["price == 110.015625"],
            ),
            SemanticTest(
                name="tsox_zero_quantity_input_required",
                description="quantity <= 0 returns status=input_required with an actionable reason.",
                inputs={"symbol": "ZN=F", "quantity": 0},
                assertions=["status == 'input_required'"],
            ),
        ],
    )


__all__ = ["tsox"]
