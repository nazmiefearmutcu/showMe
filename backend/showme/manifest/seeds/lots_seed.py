"""LOTS — Tax Lot Inventory (local ledger).

Lists, opens, sells and summarises tax lots kept in the local ShowMe tax-lot
ledger (runtime tax_lots.sqlite). The ledger is user-maintained: it is NOT a
broker feed, carries no market value and no broker-reported cost basis. TLH
and other consumers must treat its rows as the ledger's own records.
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
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def lots() -> FunctionManifest:
    return FunctionManifest(
        code="LOTS",
        name="Tax Lot Inventory",
        category=Category.PORTFOLIO,
        intent=(
            "Local tax-lot ledger: lists open lots with quantity, price, "
            "closed quantity and remaining quantity, and records opens, sells "
            "and realized gain/loss summaries. Data comes from the user's local "
            "ledger, not from a broker."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FUTURE,
            AssetClass.OPTION,
        ],
        inputs=[
            InputSpec(
                name="action",
                label="Action",
                control=ControlKind.SELECT,
                required=False,
                description="list (default), open, sell or summary.",
                options=["list", "open", "sell", "summary"],
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Filter to one symbol; omit for all open lots.",
            ),
            InputSpec(
                name="account",
                label="Account label",
                control=ControlKind.TEXT,
                required=False,
                description="Ledger account label (default 'main').",
            ),
            InputSpec(
                name="quantity",
                label="Quantity",
                control=ControlKind.NUMBER,
                required=False,
                description="Quantity for action=open or action=sell.",
                min=0,
            ),
            InputSpec(
                name="price",
                label="Price",
                control=ControlKind.NUMBER,
                required=False,
                description="Acquisition price for action=open, sale price for action=sell.",
                min=0,
            ),
            InputSpec(
                name="method",
                label="Lot selection",
                control=ControlKind.SELECT,
                required=False,
                description="Lot selection for action=sell.",
                options=["FIFO", "LIFO", "HIFO", "LOFO"],
            ),
            InputSpec(
                name="year",
                label="Year",
                control=ControlKind.NUMBER,
                required=False,
                description="Calendar year (UTC) for action=summary; omit for all years.",
                min=1970,
                max=2100,
                step=1,
            ),
        ],
        defaults={
            "action": "list",
            "method": "FIFO",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[DataMode.CACHED_SNAPSHOT, DataMode.NOT_CONFIGURED],
        ),
        caching=CachingPolicy(ttl_seconds=0, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "lots",
                "count",
                "methodology",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="lot_id", label="Lot", kind="text"),
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="account", label="Account", kind="text"),
                ColumnSpec(key="quantity", label="Quantity", kind="number", format="%.6g"),
                ColumnSpec(key="price", label="Price", kind="currency", unit="ccy", format="%.4f"),
                ColumnSpec(key="closed_qty", label="Closed", kind="number", format="%.6g"),
                ColumnSpec(key="remaining", label="Remaining", kind="number", format="%.6g"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="open_lots", label="Open Lots", kind="kpi"),
            ],
        ),
        methodology=(
            "LOTS reads the local tax-lot ledger (runtime tax_lots.sqlite). Each lot "
            "stores symbol, account, acquisition quantity and price, and the quantity "
            "already closed by sales. remaining = quantity - closed_qty. action=sell "
            "consumes open lots by FIFO, LIFO, HIFO or LOFO and records realized P&L "
            "against the ledger's own acquisition price. No broker lots, market values "
            "or unrealized P&L are produced by this function."
        ),
        formula_dict={
            "Remaining": Formula(
                expression=r"r = q - c",
                variables={"q": "Lot quantity", "c": "Closed quantity"},
            ),
        },
        field_dict={
            "lots[].lot_id": FieldDef(description="Ledger lot identifier.", source="local_ledger"),
            "lots[].symbol": FieldDef(description="Upper-case symbol of the lot.", source="local_ledger"),
            "lots[].account": FieldDef(description="Ledger account label.", source="local_ledger"),
            "lots[].quantity": FieldDef(description="Original acquired quantity.", source="local_ledger"),
            "lots[].price": FieldDef(unit="quote", description="Acquisition price per unit as entered in the ledger.", source="local_ledger"),
            "lots[].closed_qty": FieldDef(description="Quantity already sold from this lot.", source="local_ledger"),
            "lots[].remaining": FieldDef(description="quantity - closed_qty (open quantity).", source="computed"),
            "count": FieldDef(description="Number of open lots returned.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=False,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[],
            delivery=["log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="lots_list_reports_local_ledger_source",
                description="A list response names the local ledger as its only source.",
                inputs={"action": "list"},
                assertions=["sources == ['local_tax_lot_ledger']"],
            ),
            SemanticTest(
                name="lots_empty_ledger_returns_status_empty",
                description="An empty ledger returns status=empty with no lots and a next action.",
                inputs={"action": "list"},
                assertions=["status == 'empty'", "lots == []", "next_actions non-empty"],
            ),
            SemanticTest(
                name="lots_remaining_is_quantity_minus_closed",
                description="Each returned lot's remaining equals quantity minus closed_qty.",
                inputs={"action": "list"},
                assertions=["lots[].remaining == lots[].quantity - lots[].closed_qty"],
            ),
        ],
    )


__all__ = ["lots"]
