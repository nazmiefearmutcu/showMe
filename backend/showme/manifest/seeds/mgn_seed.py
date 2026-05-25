"""MGN — Margin Requirements.

Per-account margin truth: initial margin, maintenance margin, excess
liquidity, margin call distance — sourced directly from the broker. NO
client-side modeling. The semantic test pins this: margin numbers must
come from broker, never be computed.
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
def mgn() -> FunctionManifest:
    return FunctionManifest(
        code="MGN",
        name="Margin Requirements",
        category=Category.PORTFOLIO,
        intent=(
            "Per-account margin truth: initial margin, maintenance margin, "
            "excess liquidity, and distance to margin call — sourced "
            "directly from the broker. No client-side modeling of haircuts "
            "or risk weights."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FUTURE,
            AssetClass.OPTION,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="credential_id",
                label="Account",
                control=ControlKind.SELECT,
                required=True,
                description="Broker account whose margin profile to read.",
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Filter per-position margin to one symbol; omit for all.",
            ),
            InputSpec(
                name="ccy",
                label="Display currency",
                control=ControlKind.SELECT,
                required=False,
                description="Display currency for margin numbers.",
                options=["native", "USD", "EUR", "GBP", "TRY", "JPY"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; falls back to last cached broker snapshot.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "ccy": "native",
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
        caching=CachingPolicy(ttl_seconds=10, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "credential_id",
                "currency",
                "initial_margin",
                "maintenance_margin",
                "excess_liquidity",
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
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="qty", label="Qty", kind="number", format="%.6g"),
                ColumnSpec(key="market_value", label="Mkt value", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="initial_margin", label="Initial", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="maintenance_margin", label="Maint.", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="margin_rate_pct", label="Rate %", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="excess_liquidity", label="Excess Liq.", kind="big_number", unit="ccy"),
                CardSlot(key="initial_margin", label="Initial", kind="kpi", unit="ccy"),
                CardSlot(key="maintenance_margin", label="Maintenance", kind="kpi", unit="ccy"),
                CardSlot(key="maintenance_pct", label="Maint. %", kind="kpi", unit="%"),
                CardSlot(key="distance_to_call_pct", label="To call", kind="trend_pill", unit="%"),
                CardSlot(key="leverage", label="Leverage", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MGN reads broker.account() and broker.position_margin() once "
            "per refresh and surfaces the venue's authoritative margin "
            "numbers verbatim. Initial margin, maintenance margin, and "
            "excess liquidity are quoted in the broker's native currency "
            "(with optional display-ccy conversion via the FX adapter, "
            "without overriding the native value). Per-position margin is "
            "reported when the broker exposes it; otherwise rows omit the "
            "field rather than guessing. distance_to_call_pct = "
            "(equity − maintenance_margin) / equity is computed from "
            "broker-reported numbers and labelled as such. The rebuild "
            "contract forbids client-side margin modeling — if the broker "
            "does not return a value, the manifest does not synthesize one."
        ),
        formula_dict={
            "ExcessLiquidity": Formula(
                expression=r"excess = equity - maintenance\_margin",
                variables={"equity": "Broker-reported equity"},
            ),
            "DistanceToCall": Formula(
                expression=r"dist\_pct = (equity - maint) / equity \times 100",
                variables={},
                notes="From broker numbers only.",
            ),
            "Leverage": Formula(
                expression=r"L = gross\_position\_notional / equity",
                variables={},
                notes="Broker-reported when available.",
            ),
        },
        field_dict={
            "initial_margin": FieldDef(unit="ccy", description="Venue-reported initial margin requirement.", source="broker"),
            "maintenance_margin": FieldDef(unit="ccy", description="Venue-reported maintenance margin.", source="broker"),
            "excess_liquidity": FieldDef(unit="ccy", description="equity − maintenance_margin, both broker-reported.", source="computed_from_broker"),
            "distance_to_call_pct": FieldDef(unit="%", description="Cushion to maintenance breach, from broker numbers.", source="computed_from_broker"),
            "rows[].source": FieldDef(description="Always 'broker' — never synthesized.", source="broker"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "maintenance_level_below",
                "distance_to_call_below",
                "excess_liquidity_below",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="mgn_numbers_come_from_broker_not_modeled",
                description=(
                    "All margin fields trace back to the broker payload — "
                    "no client-side haircut modeling is permitted."
                ),
                inputs={"credential_id": "mock_credential_1"},
                assertions=[
                    "initial_margin.source == 'broker'",
                    "maintenance_margin.source == 'broker'",
                    "rows[].source == 'broker' for all rows",
                    "no_field_marked_as_modeled",
                ],
            ),
            SemanticTest(
                name="mgn_excess_liquidity_equals_equity_minus_maintenance",
                description="Formula is exact from broker inputs.",
                inputs={"credential_id": "mock_credential_1"},
                assertions=["excess_liquidity == equity - maintenance_margin"],
            ),
            SemanticTest(
                name="mgn_missing_field_is_omitted_not_synthesized",
                description="If broker does not return per-position margin, rows omit the field.",
                inputs={"credential_id": "mock_no_position_margin"},
                assertions=[
                    "rows have no maintenance_margin field",
                    "warning_says_broker_did_not_expose",
                ],
            ),
            SemanticTest(
                name="mgn_missing_credential_returns_not_configured",
                description="Unknown credential id returns data_mode=not_configured.",
                inputs={"credential_id": "does_not_exist"},
                assertions=[
                    "data_mode == 'not_configured'",
                    "warnings_non_empty",
                ],
            ),
        ],
    )


__all__ = ["mgn"]
