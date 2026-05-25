"""WACC — Weighted Average Cost of Capital.

WACC = (E/V) × R_e + (D/V) × R_d × (1 − T). R_e is CAPM: rf + β × ERP.
Inputs come from FRED (rf, R_d), yfinance (E, D, country / tax), the
BetaFunction (β), and a Damodaran ERP scrape (configurable). The handler
echoes the assumption dict so the consumer can audit which WACC they read.
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
def wacc() -> FunctionManifest:
    return FunctionManifest(
        code="WACC",
        name="Weighted Average Cost of Capital",
        category=Category.EQUITIES,
        intent=(
            "Compute the company's weighted average cost of capital from CAPM cost of equity, "
            "after-tax cost of debt, and the equity / debt split."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker.",
            ),
            InputSpec(
                name="market_premium",
                label="Equity risk premium (ERP)",
                control=ControlKind.MODEL_ASSUMPTION,
                required=True,
                description="Market premium over the risk-free rate.",
                min=0.02,
                max=0.12,
                step=0.0025,
                unit="decimal",
            ),
            InputSpec(
                name="beta_window",
                label="Beta window",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Lookback window passed to BetaFunction.",
                options=["60d", "126d", "252d", "504d", "756d"],
            ),
            InputSpec(
                name="tax_rate_override",
                label="Tax rate override",
                control=ControlKind.MODEL_ASSUMPTION,
                required=False,
                description="Override the effective tax rate; default uses FA-derived T.",
                min=0.0,
                max=0.45,
                step=0.005,
                unit="decimal",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode for the upstream FA pull.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "market_premium": 0.05,
            "beta_window": "252d",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance", "sec_edgar", "fred", "cached_snapshot"],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "symbol",
                "status",
                "wacc",
                "re_capm",
                "rf",
                "beta",
                "erp",
                "rd",
                "tax_rate",
                "equity_weight",
                "debt_weight",
                "assumptions",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="component", label="Component", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.4f"),
                ColumnSpec(key="formula", label="Formula", kind="text"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="wacc", label="WACC", kind="big_number", unit="%"),
                CardSlot(key="re_capm", label="R_e (CAPM)", kind="kpi", unit="%"),
                CardSlot(key="rd", label="R_d", kind="kpi", unit="%"),
                CardSlot(key="beta", label="β", kind="kpi"),
                CardSlot(key="equity_weight", label="E/V", kind="kpi", unit="%"),
                CardSlot(key="debt_weight", label="D/V", kind="kpi", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "WACC pulls rf from FRED (DGS10 by default), R_d from FRED corporate Aaa/Baa yields, "
            "the effective tax rate T from FA (or override), and the market-value equity / debt "
            "split from FA / yfinance. β is computed by the shared BetaFunction at the requested "
            "window. R_e is the CAPM expression rf + β × ERP. WACC = (E/V) × R_e + (D/V) × R_d × "
            "(1 − T). The handler renders the β × R_d sensitivity surface (3 × 3) so the operator "
            "can read the WACC range at a glance, and echoes the assumption dict so the consumer "
            "can audit which WACC they read."
        ),
        formula_dict={
            "WACC": Formula(
                expression=r"WACC = \frac{E}{V} \cdot R_e + \frac{D}{V} \cdot R_d \cdot (1 - T)",
                variables={
                    "E": "Market value of equity",
                    "D": "Market value of debt",
                    "V": "E + D",
                    "R_e": "Cost of equity (CAPM)",
                    "R_d": "Pre-tax cost of debt",
                    "T": "Effective tax rate",
                },
                notes="Tax shield applies to the debt component only.",
            ),
            "CAPM": Formula(
                expression=r"R_e = r_f + \beta \cdot ERP",
                variables={
                    "r_f": "Risk-free rate (FRED DGS10 by default)",
                    "beta": "Equity beta vs market",
                    "ERP": "Equity risk premium (market_premium input)",
                },
            ),
        },
        field_dict={
            "wacc": FieldDef(unit="decimal annualized", description="Weighted average cost of capital.", source="computed"),
            "re_capm": FieldDef(unit="decimal annualized", description="Cost of equity via CAPM.", source="computed"),
            "rf": FieldDef(unit="decimal annualized", description="Risk-free rate (FRED DGS10).", source="fred"),
            "beta": FieldDef(description="Equity beta from BetaFunction.", source="internal"),
            "erp": FieldDef(unit="decimal", description="Equity risk premium (input or Damodaran).", source="input"),
            "rd": FieldDef(unit="decimal annualized", description="Pre-tax cost of debt.", source="fred"),
            "tax_rate": FieldDef(unit="decimal", description="Effective tax rate (FA or override).", source="provider"),
            "equity_weight": FieldDef(unit="decimal", description="E / (E+D).", source="computed"),
            "debt_weight": FieldDef(unit="decimal", description="D / (E+D).", source="computed"),
            "assumptions": FieldDef(description="Echoed inputs (market_premium, beta_window, tax_rate_override).", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="wacc_aapl_default_assumptions_returns_finite_wacc",
                description="WACC for AAPL with default assumptions returns a finite WACC ∈ (0, 0.3).",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_in_ok_set",
                    "wacc_is_finite_number",
                    "wacc_between_0_and_0_3",
                ],
            ),
            SemanticTest(
                name="wacc_assumptions_visible_in_output",
                description="The output echoes ERP / beta_window so the consumer can audit which WACC they read.",
                inputs={"symbol": "AAPL", "market_premium": 0.06, "beta_window": "126d"},
                assertions=[
                    "assumptions_visible_in_output",
                    "assumptions_market_premium_equals_input",
                    "assumptions_beta_window_equals_input",
                ],
            ),
            SemanticTest(
                name="wacc_provider_outage_returns_unavailable",
                description="When FRED + FA both fail, status=provider_unavailable; WACC is null not stubbed.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "wacc_is_null",
                    "next_actions_non_empty",
                ],
            ),
        ],
    )


__all__ = ["wacc"]
