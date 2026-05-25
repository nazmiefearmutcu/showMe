"""TRA — Transaction Analysis (per-fill).

Detailed per-fill ledger from the broker: time, side, qty, price,
commission, slippage vs arrival, and venue. Backbone for execution
quality reviews and lifetime PnL reconciliation.
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
def tra() -> FunctionManifest:
    return FunctionManifest(
        code="TRA",
        name="Transaction Analysis",
        category=Category.PORTFOLIO,
        intent=(
            "Detailed per-fill ledger from the broker: time, side, qty, "
            "price, commission, slippage vs arrival price, venue, and any "
            "client-side audit metadata. Backbone for execution-quality "
            "reviews and lifetime PnL reconciliation."
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
                name="credential_id",
                label="Account",
                control=ControlKind.SELECT,
                required=True,
                description="Broker account whose fills to inspect.",
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Filter to one symbol; omit for all fills.",
            ),
            InputSpec(
                name="date_range",
                label="Date range",
                control=ControlKind.DATE_RANGE,
                required=True,
                description="Window to fetch fills for. Defaults to last 30d.",
            ),
            InputSpec(
                name="side_filter",
                label="Side",
                control=ControlKind.SELECT,
                required=False,
                description="Filter by buy / sell / both.",
                options=["buy", "sell", "both"],
            ),
            InputSpec(
                name="min_notional",
                label="Min notional",
                control=ControlKind.NUMBER,
                required=False,
                description="Hide fills smaller than this notional.",
                min=0,
                max=10000000,
                step=10,
                unit="ccy",
            ),
            InputSpec(
                name="include_audit",
                label="Include audit data",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Join client-side audit_ledger rows (client request id, latency, retries).",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; falls back to local audit ledger.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "side_filter": "both",
            "min_notional": 0,
            "include_audit": True,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
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
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "credential_id",
                "fills",
                "totals",
                "data_mode",
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
                ColumnSpec(key="fill_id", label="Fill", kind="text"),
                ColumnSpec(key="fill_time", label="Time", kind="datetime"),
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="side", label="Side", kind="tag"),
                ColumnSpec(key="qty", label="Qty", kind="number", format="%.6g"),
                ColumnSpec(key="price", label="Fill Px", kind="currency", unit="ccy", format="%.4f"),
                ColumnSpec(key="notional", label="Notional", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="commission", label="Comm.", kind="currency", unit="ccy", format="%.4f"),
                ColumnSpec(key="arrival_price", label="Arrival", kind="currency", unit="ccy", format="%.4f"),
                ColumnSpec(key="slippage_bps", label="Slippage", kind="number", unit="bps", format="%.1f"),
                ColumnSpec(key="venue", label="Venue", kind="tag"),
                ColumnSpec(key="order_id", label="Order", kind="text"),
                ColumnSpec(key="client_request_id", label="Audit", kind="text"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="fills_count", label="Fills", kind="kpi"),
                CardSlot(key="total_notional", label="Total Notional", kind="big_number", unit="ccy"),
                CardSlot(key="total_commission", label="Total Comm.", kind="kpi", unit="ccy"),
                CardSlot(key="avg_slippage_bps", label="Avg Slip", kind="kpi", unit="bps"),
                CardSlot(key="buy_count", label="Buys", kind="kpi"),
                CardSlot(key="sell_count", label="Sells", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TRA fetches per-fill records from the broker for the chosen "
            "date_range (broker.fills() or trade-history endpoint). Each "
            "fill carries time, side, qty, price, commission, venue, and "
            "order_id. Slippage in bps = (fill_price − arrival_price) / "
            "arrival_price × 10000, signed against the trade side so a "
            "negative slippage is always 'better than arrival'. Arrival "
            "price comes from the client-side audit_ledger (recorded when "
            "the order was submitted) when include_audit=true; otherwise "
            "the broker's reported reference price is used. When the "
            "broker does not publish per-fill commissions (some crypto "
            "exchanges), the field is omitted rather than synthesized. "
            "Audit join surfaces client_request_id + retry counts to "
            "diagnose execution incidents."
        ),
        formula_dict={
            "Slippage": Formula(
                expression=r"slip\_bps = (p_{fill} - p_{arr}) / p_{arr} \times 10000",
                variables={"p_arr": "Arrival reference price"},
                notes="Sign-flipped on sell side so 'better than arrival' is always negative.",
            ),
            "AvgSlippage": Formula(
                expression=r"\bar{slip} = \sum_i |n_i| slip_i / \sum_i |n_i|",
                variables={"n_i": "Per-fill notional"},
                notes="Notional-weighted.",
            ),
            "FillCost": Formula(
                expression=r"cost_i = n_i + commission_i",
                variables={},
            ),
        },
        field_dict={
            "fills[].fill_id": FieldDef(description="Broker-assigned execution id.", source="broker"),
            "fills[].arrival_price": FieldDef(unit="quote", description="Reference price at submit time, from audit_ledger.", source="audit_ledger"),
            "fills[].slippage_bps": FieldDef(unit="bps", description="Side-aware slippage vs arrival.", source="computed"),
            "fills[].venue": FieldDef(description="Execution venue (if disclosed).", source="broker"),
            "fills[].client_request_id": FieldDef(description="Optional client-side request id for audit traceability.", source="audit_ledger"),
            "totals.total_notional": FieldDef(unit="ccy", description="Σ |notional| across filtered fills.", source="computed"),
            "totals.avg_slippage_bps": FieldDef(unit="bps", description="Notional-weighted average slippage.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="tra_fills_traceable_to_orders",
                description="Each fill row carries an order_id that links back to the originating order.",
                inputs={},
                assertions=["all fills have non-empty order_id"],
            ),
            SemanticTest(
                name="tra_slippage_sign_convention",
                description="Buy filled above arrival → positive slippage; sell filled above arrival → negative slippage.",
                inputs={},
                assertions=[
                    "buy_above_arrival_slip > 0",
                    "sell_above_arrival_slip < 0",
                ],
            ),
            SemanticTest(
                name="tra_missing_commission_omitted_not_synthesized",
                description="When broker does not return commission, the field is omitted, not zeroed.",
                inputs={},
                assertions=["fill rows for venues_without_commission omit commission field"],
            ),
            SemanticTest(
                name="tra_missing_credential_returns_not_configured",
                description="Unknown credential id returns data_mode=not_configured.",
                inputs={"credential_id": "does_not_exist"},
                assertions=[
                    "data_mode == 'not_configured'",
                    "warnings_non_empty",
                ],
            ),
        ],
    )


__all__ = ["tra"]
