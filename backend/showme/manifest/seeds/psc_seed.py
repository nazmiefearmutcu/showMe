"""PSC — Price Scenario Center.

Single-symbol what-if. Pick a symbol, define a price/return shock, see
the linear P&L effect on every position that holds that symbol (or any
correlated symbol if propagate=True). Lightweight cousin of STRS.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
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
def psc() -> FunctionManifest:
    return FunctionManifest(
        code="PSC",
        name="Price Scenario Center",
        category=Category.PORTFOLIO,
        intent=(
            "Single-symbol what-if. Pick a symbol, apply a price or return "
            "shock, and see the P&L impact across the portfolio — direct "
            "effect on the named symbol plus optional correlation-implied "
            "spillover to correlated holdings."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.OPTION,
            AssetClass.FUTURE,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Instrument whose price you want to shock.",
            ),
            InputSpec(
                name="shock_type",
                label="Shock type",
                control=ControlKind.SELECT,
                required=True,
                description="How the shock is expressed.",
                options=["absolute_price", "pct_change", "sigma"],
            ),
            InputSpec(
                name="shock_magnitude",
                label="Magnitude",
                control=ControlKind.NUMBER,
                required=True,
                description=(
                    "Shock magnitude. Sign convention: negative = down. "
                    "Units depend on shock_type."
                ),
                min=-1000000.0,
                max=1000000.0,
                step=0.01,
            ),
            InputSpec(
                name="propagate",
                label="Propagate via correlations",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "When true, also shock correlated holdings using the "
                    "historical correlation matrix from PORT's window."
                ),
            ),
            InputSpec(
                name="lookback_window",
                label="Lookback (for ρ)",
                control=ControlKind.SELECT,
                required=False,
                description="Window used for the correlation matrix when propagate=true.",
                options=["30d", "90d", "180d", "1Y"],
                depends_on=["propagate"],
            ),
            InputSpec(
                name="paper_mode",
                label="Paper mode (safe)",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Research-only; no live execution path.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for price + correlation history.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "shock_type": "pct_change",
            "shock_magnitude": -0.05,
            "propagate": False,
            "lookback_window": "90d",
            "paper_mode": True,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "binance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "as_of",
                "symbol",
                "shock_applied",
                "direct_impact",
                "total_impact",
                "affected_positions",
                "data_mode",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="category", unit="", label="Position"),
            y_axis=AxisSpec(type="numeric", unit="ccy", label="P&L Δ"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="position_symbol", label="Symbol", kind="text"),
                ColumnSpec(key="qty", label="Qty", kind="number", format="%.4g"),
                ColumnSpec(key="implied_price_change", label="Implied Δp", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="impact_value", label="P&L Δ", kind="currency", unit="ccy", format="%.0f"),
                ColumnSpec(key="impact_pct", label="P&L Δ%", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_impact", label="Total Δ", kind="big_number", unit="ccy"),
                CardSlot(key="direct_impact", label="Direct", kind="kpi", unit="ccy"),
                CardSlot(key="spillover_impact", label="Spillover", kind="kpi", unit="ccy"),
                CardSlot(key="affected_count", label="Positions", kind="kpi"),
                CardSlot(key="paper_mode", label="Mode", kind="badge"),
                CardSlot(key="data_mode", label="Data", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "PSC applies the requested shock to the named symbol and "
            "computes the linear P&L effect across the portfolio. Direct "
            "impact: any position holding the named symbol gets Δp × qty. "
            "If propagate=true, the historical correlation matrix from the "
            "selected window maps the named symbol's return shock to "
            "implied returns on every correlated holding (Δr_j ≈ ρ_jk × Δr_k "
            "× σ_j/σ_k); the implied per-position P&L is then qty_j × p_j × "
            "Δr_j. Total impact = direct + spillover. Shock types: "
            "absolute_price replaces last with the supplied number; "
            "pct_change multiplies; sigma multiplies by daily realized σ. "
            "Linear approximation only — does not capture convexity (option "
            "gamma, bond convexity); use STRS or GREEKS for non-linear "
            "stress."
        ),
        formula_dict={
            "DirectImpact": Formula(
                expression=r"\Delta_{direct} = qty \cdot \Delta p",
                variables={"qty": "Position size in named symbol"},
            ),
            "Spillover": Formula(
                expression=r"\Delta r_j = \rho_{jk} \cdot \Delta r_k \cdot \sigma_j / \sigma_k",
                variables={"ρ_jk": "Pair correlation", "σ": "Per-asset volatility"},
            ),
            "TotalImpact": Formula(
                expression=r"\Delta_{total} = \Delta_{direct} + \sum_j qty_j \cdot p_j \cdot \Delta r_j",
                variables={},
            ),
        },
        field_dict={
            "shock_applied": FieldDef(unit="", description="Echo of the input shock for traceability.", source="input"),
            "direct_impact": FieldDef(unit="ccy", description="P&L change on positions in the named symbol.", source="computed"),
            "spillover_impact": FieldDef(unit="ccy", description="P&L change from correlation-implied moves.", source="computed"),
            "total_impact": FieldDef(unit="ccy", description="direct + spillover.", source="computed"),
            "affected_positions[]": FieldDef(unit="", description="Per-position breakdown with source tag.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="psc_paper_mode_defaults_true",
                description="Research surface is paper-safe by default.",
                inputs={},
                assertions=["defaults.paper_mode == True"],
            ),
            SemanticTest(
                name="psc_no_propagate_means_only_direct",
                description="With propagate=false, total_impact == direct_impact.",
                inputs={"propagate": False},
                assertions=["total_impact == direct_impact"],
            ),
            SemanticTest(
                name="psc_symbol_not_held_returns_zero_direct",
                description="If the named symbol is not in the portfolio, direct_impact = 0.",
                inputs={},
                assertions=["direct_impact == 0 when symbol_not_held"],
            ),
            SemanticTest(
                name="psc_zero_shock_is_zero_impact",
                description="shock_magnitude=0 → total_impact=0 exactly.",
                inputs={"shock_magnitude": 0.0},
                assertions=["total_impact == 0.0"],
            ),
        ],
    )


__all__ = ["psc"]
