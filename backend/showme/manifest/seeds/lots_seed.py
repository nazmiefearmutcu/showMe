"""LOTS — Tax Lot Inventory.

Per-position tax lot ledger sourced directly from the broker. Shows
acquisition date, qty, cost basis, holding period, and short/long-term
status. LOTS is the data backbone TLH consumes.
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
            "Per-position tax-lot ledger sourced directly from the broker: "
            "acquisition date, qty, cost basis, holding period, current "
            "value, and short-vs-long-term status. Backbone data for TLH."
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
                name="credential_id",
                label="Account",
                control=ControlKind.SELECT,
                required=True,
                description="Broker account to pull lots from.",
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Filter to one symbol; omit for all open lots.",
            ),
            InputSpec(
                name="status",
                label="Lot status",
                control=ControlKind.SELECT,
                required=False,
                description="Open lots, closed lots (for realized accounting), or all.",
                options=["open", "closed", "all"],
            ),
            InputSpec(
                name="holding_period_filter",
                label="Holding period",
                control=ControlKind.SELECT,
                required=False,
                description="Short-term, long-term, or both.",
                options=["short_term", "long_term", "all"],
            ),
            InputSpec(
                name="long_term_threshold_days",
                label="Long-term threshold",
                control=ControlKind.NUMBER,
                required=False,
                description="Days of holding to qualify as long-term (US default 365).",
                min=1,
                max=730,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; falls back to last broker snapshot.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "status": "open",
            "holding_period_filter": "all",
            "long_term_threshold_days": 365,
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
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "credential_id",
                "lots",
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
                ColumnSpec(key="lot_id", label="Lot", kind="text"),
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="acquired_at", label="Acquired", kind="date"),
                ColumnSpec(key="qty", label="Qty", kind="number", format="%.6g"),
                ColumnSpec(key="cost_basis_per_unit", label="Basis/unit", kind="currency", unit="ccy", format="%.4f"),
                ColumnSpec(key="cost_basis_total", label="Basis total", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="market_value", label="Mkt value", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="unrealized", label="Unrealized", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="unrealized_pct", label="Unr. %", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="holding_days", label="Held", kind="number", unit="d", format="%d"),
                ColumnSpec(key="term", label="Term", kind="tag"),
                ColumnSpec(key="status", label="Status", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="open_lots", label="Open Lots", kind="kpi"),
                CardSlot(key="total_basis", label="Total Basis", kind="big_number", unit="ccy"),
                CardSlot(key="total_mv", label="Total MV", kind="big_number", unit="ccy"),
                CardSlot(key="total_unrealized", label="Unrealized", kind="trend_pill", unit="ccy"),
                CardSlot(key="lt_pct", label="Long-term %", kind="kpi", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "LOTS pulls the per-lot ledger directly from the broker via "
            "the broker.lots() call (CCXT-bridged where possible; falls "
            "back to local audit ledger reconstruction when the broker "
            "does not expose lot detail). For each open lot, holding_days = "
            "(today - acquired_at).days, term = 'long_term' if "
            "holding_days >= long_term_threshold_days else 'short_term'. "
            "Cost basis is the broker's reported number — no FIFO/LIFO "
            "imputation is performed (that's the broker's authority). "
            "Market value uses the same live quote adapter as PORT. "
            "Closed lots include realization date, proceeds, and the "
            "broker-determined cost basis (used by TLH to identify "
            "harvestable losses without re-running matching here)."
        ),
        formula_dict={
            "Unrealized": Formula(
                expression=r"u = (p_{last} - basis) \cdot qty",
                variables={"basis": "Cost basis per unit", "p_last": "Last price"},
            ),
            "HoldingDays": Formula(
                expression=r"d = (today - acquired\_at).days",
                variables={},
            ),
            "Term": Formula(
                expression=r"term = LT \text{ if } d \geq threshold \text{ else } ST",
                variables={"threshold": "Jurisdiction long-term cutoff"},
            ),
        },
        field_dict={
            "lots[].lot_id": FieldDef(description="Broker-assigned lot identifier.", source="broker"),
            "lots[].acquired_at": FieldDef(description="Lot acquisition timestamp.", source="broker"),
            "lots[].cost_basis_per_unit": FieldDef(unit="quote", description="Per-unit cost basis as reported by broker.", source="broker"),
            "lots[].qty": FieldDef(description="Remaining (open) or original (closed) lot quantity.", source="broker"),
            "lots[].term": FieldDef(description="short_term or long_term per holding_days.", source="computed"),
            "totals.total_basis": FieldDef(unit="ccy", description="Σ cost_basis_total across filtered lots.", source="computed"),
            "totals.total_unrealized": FieldDef(unit="ccy", description="Σ unrealized across filtered lots.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["lot_crossing_long_term_threshold"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="lots_term_is_long_when_held_above_threshold",
                description="Lot held 366 days with default threshold returns term='long_term'.",
                inputs={"long_term_threshold_days": 365},
                assertions=["lot_held_366d_term == 'long_term'"],
            ),
            SemanticTest(
                name="lots_term_is_short_when_held_below_threshold",
                description="Lot held 364 days returns term='short_term'.",
                inputs={"long_term_threshold_days": 365},
                assertions=["lot_held_364d_term == 'short_term'"],
            ),
            SemanticTest(
                name="lots_totals_equal_sum_of_filtered_lots",
                description="totals.total_basis equals sum of cost_basis_total across rows.",
                inputs={},
                assertions=["totals.total_basis == sum(lots[].cost_basis_total)"],
            ),
            SemanticTest(
                name="lots_missing_credential_returns_not_configured",
                description="Unknown credential id returns data_mode=not_configured with warning.",
                inputs={"credential_id": "does_not_exist"},
                assertions=[
                    "data_mode == 'not_configured'",
                    "warnings_non_empty",
                ],
            ),
        ],
    )


__all__ = ["lots"]
