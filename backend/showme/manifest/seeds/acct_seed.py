"""ACCT — Account Truth (balance, margin, equity, buying power).

Per-broker account-level snapshot sourced directly from each broker's
``account()`` call. PORT aggregates across many credentials; ACCT
shows one credential's authoritative numbers without computation, so
the user can reconcile their own broker UI against the showMe ledger.
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
def acct() -> FunctionManifest:
    return FunctionManifest(
        code="ACCT",
        name="Account Truth",
        category=Category.PORTFOLIO,
        intent=(
            "Show one connected broker's authoritative account snapshot — "
            "equity, cash, margin used, free margin, maintenance level, and "
            "buying power — exactly as the broker reports it."
        ),
        asset_classes=[
            AssetClass.EQUITY,
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
                description="Pick one credential from the exchange vault.",
            ),
            InputSpec(
                name="ccy",
                label="Display currency",
                control=ControlKind.SELECT,
                required=False,
                description=(
                    "If broker reports in a different currency, convert via "
                    "the FX adapter. Native ccy is always also shown."
                ),
                options=["native", "USD", "EUR", "GBP", "TRY", "JPY"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade and report it.",
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
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "credential_id", "currency", "equity", "cash", "data_mode"],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=None,
        card_schema=CardSchema(
            slots=[
                CardSlot(key="equity", label="Equity", kind="big_number", unit="ccy"),
                CardSlot(key="cash", label="Cash", kind="kpi", unit="ccy"),
                CardSlot(key="margin_used", label="Margin Used", kind="kpi", unit="ccy"),
                CardSlot(key="free_margin", label="Free Margin", kind="kpi", unit="ccy"),
                CardSlot(key="maintenance_level_pct", label="Maint. %", kind="kpi", unit="%"),
                CardSlot(key="buying_power", label="Buying Power", kind="kpi", unit="ccy"),
                CardSlot(key="leverage", label="Leverage", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ACCT resolves the chosen credential through the broker factory, "
            "calls the broker's account() method exactly once per refresh, "
            "and surfaces the raw numbers without recomputation. Margin and "
            "maintenance levels come straight from the venue (so the user "
            "can reconcile against the broker's own UI). Optional display-ccy "
            "conversion uses the same FX adapter as PORT, with the native "
            "currency value always preserved alongside. No positions are "
            "joined here — that is PORT's job."
        ),
        formula_dict={
            "FreeMargin": Formula(
                expression="free = equity - margin_used",
                variables={"equity": "Broker-reported equity", "margin_used": "Notional used"},
            ),
            "MaintenanceLevel": Formula(
                expression=r"maint\_pct = margin\_used / equity \times 100",
                variables={},
                notes="Below the venue's maintenance threshold triggers a margin call.",
            ),
        },
        field_dict={
            "equity": FieldDef(unit="ccy", description="Broker equity = cash + unrealized PnL.", source="broker"),
            "cash": FieldDef(unit="ccy", description="Settled cash balance.", source="broker"),
            "margin_used": FieldDef(unit="ccy", description="Notional collateral locked by open positions.", source="broker"),
            "free_margin": FieldDef(unit="ccy", description="equity − margin_used.", source="computed"),
            "maintenance_level_pct": FieldDef(unit="%", description="Current maintenance margin level.", source="broker"),
            "buying_power": FieldDef(unit="ccy", description="Available notional for new positions.", source="broker"),
            "leverage": FieldDef(unit="x", description="Account-wide leverage if exposed by the venue.", source="broker"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["maintenance_level_below", "free_margin_below", "equity_drawdown_pct"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="acct_returns_native_currency_when_ccy_native",
                description="ccy=native returns broker's native equity, cash, margin without FX conversion.",
                inputs={"credential_id": "mock_credential_1", "ccy": "native"},
                assertions=[
                    "currency == broker_native_currency",
                    "no_fx_conversion_applied",
                ],
            ),
            SemanticTest(
                name="acct_free_margin_equals_equity_minus_margin_used",
                description="Computed free_margin matches the documented formula exactly.",
                inputs={"credential_id": "mock_credential_1"},
                assertions=["free_margin == equity - margin_used"],
            ),
            SemanticTest(
                name="acct_missing_credential_returns_not_configured",
                description="Unknown credential id returns data_mode=not_configured plus an actionable warning.",
                inputs={"credential_id": "does_not_exist"},
                assertions=[
                    "data_mode == 'not_configured'",
                    "warnings_non_empty",
                ],
            ),
        ],
    )


__all__ = ["acct"]
