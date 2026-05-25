"""GREEKS — Portfolio Greeks roll-up.

For option-bearing portfolios, aggregate per-position Greeks (Δ, Γ, Θ,
Vega, Rho) into book-level numbers using Black-Scholes-Merton (or
broker-supplied when available). Sourced primarily from broker; internal
BSM is the fallback for venues that do not publish Greeks.
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
def greeks() -> FunctionManifest:
    return FunctionManifest(
        code="GREEKS",
        name="Portfolio Greeks",
        category=Category.PORTFOLIO,
        intent=(
            "Roll up per-position option Greeks (Δ, Γ, Θ, Vega, Rho) into "
            "book-level totals. Source order: broker-provided when "
            "available; internal Black-Scholes-Merton fallback for venues "
            "that do not publish Greeks."
        ),
        asset_classes=[
            AssetClass.OPTION,
            AssetClass.EQUITY,
            AssetClass.FUTURE,
            AssetClass.CRYPTO,
        ],
        inputs=[
            InputSpec(
                name="credential_id",
                label="Account",
                control=ControlKind.SELECT,
                required=True,
                description="Broker account whose option book to aggregate.",
            ),
            InputSpec(
                name="as_of",
                label="As of",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Snapshot date; default = live.",
            ),
            InputSpec(
                name="group_by",
                label="Group by",
                control=ControlKind.SELECT,
                required=True,
                description="Roll-up dimension.",
                options=["underlying", "expiry", "strike", "none"],
            ),
            InputSpec(
                name="vol_model",
                label="Vol model (fallback)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description=(
                    "Volatility used by the internal BSM fallback when "
                    "broker does not publish Greeks."
                ),
                options=["broker_iv", "atm_iv", "historical_30d", "user_supplied"],
            ),
            InputSpec(
                name="risk_free_rate",
                label="Risk-free rate",
                control=ControlKind.NUMBER,
                required=False,
                description="Annualized r used by internal BSM.",
                min=-0.05,
                max=0.25,
                step=0.0001,
                unit="decimal",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for option chain + vol.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "group_by": "underlying",
            "vol_model": "broker_iv",
            "risk_free_rate": 0.045,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="ccxt_broker",
            fallbacks=["cboe_options", "internal", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "credential_id",
                "totals",
                "groups",
                "data_mode",
                "source_kind",
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
                ColumnSpec(key="key", label="Group", kind="text"),
                ColumnSpec(key="contracts", label="Contracts", kind="number", format="%d"),
                ColumnSpec(key="delta", label="Δ", kind="number", format="%.2f"),
                ColumnSpec(key="gamma", label="Γ", kind="number", format="%.4f"),
                ColumnSpec(key="theta", label="Θ (1d)", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="vega", label="Vega", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="rho", label="Rho", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="net_delta", label="Net Δ", kind="big_number"),
                CardSlot(key="net_gamma", label="Net Γ", kind="kpi"),
                CardSlot(key="net_theta_daily", label="Θ / day", kind="kpi", unit="ccy"),
                CardSlot(key="net_vega", label="Net Vega", kind="kpi", unit="ccy"),
                CardSlot(key="net_rho", label="Net Rho", kind="kpi", unit="ccy"),
                CardSlot(key="source_kind", label="Source", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "GREEKS aggregates option positions in the chosen credential. "
            "For each contract: if the broker publishes Greeks "
            "(Interactive Brokers, Tastytrade), they are used verbatim and "
            "tagged source='broker'. If not, internal Black-Scholes-Merton "
            "computes Δ, Γ, Θ, Vega, Rho from spot, strike, expiry, "
            "implied vol, and risk_free_rate, tagged source='bsm_modeled'. "
            "Aggregation: positional contribution = qty × multiplier × "
            "per-contract Greek (sign-aware for short positions). Group "
            "rows show same numbers rolled up by underlying / expiry / "
            "strike. The source_kind field on the response tells the user "
            "which Greeks were broker-truth and which were modeled — never "
            "silently mix without disclosure."
        ),
        formula_dict={
            "Delta": Formula(
                expression=r"\Delta = N(d_1) \text{ (call)}, \; N(d_1) - 1 \text{ (put)}",
                variables={"d_1": "BSM d1"},
            ),
            "Gamma": Formula(
                expression=r"\Gamma = \phi(d_1) / (S \sigma \sqrt{T})",
                variables={"φ": "Standard-normal pdf"},
            ),
            "Theta": Formula(
                expression=r"\Theta = -S \phi(d_1) \sigma / (2\sqrt{T}) \pm r K e^{-rT} N(\pm d_2)",
                variables={},
                notes="Daily Θ = annual Θ / 365.",
            ),
            "Vega": Formula(
                expression=r"\nu = S \sqrt{T} \phi(d_1)",
                variables={},
                notes="Per 1.0 change in σ; commonly displayed per 1% (Vega/100).",
            ),
            "Aggregation": Formula(
                expression=r"\Delta_{book} = \sum_i sign_i \cdot qty_i \cdot mult_i \cdot \Delta_i",
                variables={"sign_i": "+1 long, -1 short"},
            ),
        },
        field_dict={
            "totals.net_delta": FieldDef(description="Σ position-weighted Δ across the book.", source="aggregated"),
            "totals.net_gamma": FieldDef(description="Σ position-weighted Γ.", source="aggregated"),
            "totals.net_theta_daily": FieldDef(unit="ccy", description="Per-day time decay across the book.", source="aggregated"),
            "totals.net_vega": FieldDef(unit="ccy", description="Σ Vega across the book.", source="aggregated"),
            "totals.net_rho": FieldDef(unit="ccy", description="Σ Rho across the book.", source="aggregated"),
            "source_kind": FieldDef(description="broker | bsm_modeled | mixed.", source="computed"),
            "groups[].source": FieldDef(description="Per-group provenance flag.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["net_delta_outside_band", "net_vega_outside_band"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="greeks_source_kind_distinguishes_broker_vs_modeled",
                description="When broker publishes Greeks, source_kind='broker'; when BSM fills gaps, source_kind='mixed' or 'bsm_modeled'.",
                inputs={},
                assertions=[
                    "source_kind in ['broker', 'bsm_modeled', 'mixed']",
                    "groups[].source flagged accordingly",
                ],
            ),
            SemanticTest(
                name="greeks_short_position_sign_inverts_delta",
                description="Short call: contribution to net_delta is negative.",
                inputs={},
                assertions=["short_call_delta_contribution < 0"],
            ),
            SemanticTest(
                name="greeks_no_options_returns_empty_with_explanation",
                description="Account with no option positions returns empty totals.",
                inputs={},
                assertions=["net_delta == 0", "warnings includes 'no option positions'"],
            ),
            SemanticTest(
                name="greeks_missing_credential_returns_not_configured",
                description="Unknown credential id returns data_mode=not_configured.",
                inputs={"credential_id": "does_not_exist"},
                assertions=[
                    "data_mode == 'not_configured'",
                    "warnings_non_empty",
                ],
            ),
        ],
    )


__all__ = ["greeks"]
