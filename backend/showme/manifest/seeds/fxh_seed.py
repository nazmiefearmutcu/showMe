"""FXH — FX Exposure Hedge Calculator.

Given an FX exposure (notional in foreign currency), the tenor, the
hedge ratio, and a candidate spot shock, computes: hedge notional,
residual exposure, P/L under the shock with and without the hedge,
and the cost of the hedge (forward points + assumed bid-ask).
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
def fxh() -> FunctionManifest:
    return FunctionManifest(
        code="FXH",
        name="FX Exposure Hedge Calculator",
        category=Category.FX,
        intent=(
            "Hedge calculator for an FX exposure: given exposure × tenor × "
            "hedge_ratio × spot_shock, returns hedge notional, residual "
            "exposure, P/L under the shock, and the cost of the hedge."
        ),
        asset_classes=[AssetClass.FX],
        inputs=[
            InputSpec(
                name="pair",
                label="Pair",
                control=ControlKind.SELECT,
                required=True,
                description="FX pair the exposure is denominated in.",
                options=[
                    "EURUSD",
                    "USDJPY",
                    "GBPUSD",
                    "AUDUSD",
                    "USDCAD",
                    "USDCHF",
                    "USDTRY",
                ],
            ),
            InputSpec(
                name="exposure_notional",
                label="Exposure (foreign ccy)",
                control=ControlKind.NUMBER,
                required=True,
                description="Notional exposure denominated in the foreign currency leg.",
                step=1.0,
                unit="foreign_ccy",
            ),
            InputSpec(
                name="exposure_side",
                label="Exposure side",
                control=ControlKind.SELECT,
                required=True,
                description="Long = receive foreign, short = pay foreign.",
                options=["long_foreign", "short_foreign"],
            ),
            InputSpec(
                name="tenor",
                label="Tenor",
                control=ControlKind.HORIZON,
                required=True,
                description="Hedge tenor.",
                options=["1W", "1M", "3M", "6M", "1Y"],
            ),
            InputSpec(
                name="hedge_ratio",
                label="Hedge ratio",
                control=ControlKind.NUMBER,
                required=True,
                description="Fraction of notional to hedge (0.0 = no hedge, 1.0 = full hedge).",
                min=0.0,
                max=1.0,
                step=0.01,
                unit="decimal",
            ),
            InputSpec(
                name="spot_shock_pct",
                label="Spot shock (%)",
                control=ControlKind.NUMBER,
                required=True,
                description="Hypothetical spot move (positive = base appreciates vs quote).",
                min=-50.0,
                max=50.0,
                step=0.1,
                unit="%",
            ),
            InputSpec(
                name="bid_ask_pips",
                label="Hedge bid-ask (pips)",
                control=ControlKind.NUMBER,
                required=False,
                description="Assumed transaction cost in pips for sizing.",
                min=0.0,
                step=0.1,
                unit="pips",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode for the spot quote.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                ],
            ),
        ],
        defaults={
            "pair": "EURUSD",
            "exposure_side": "long_foreign",
            "tenor": "3M",
            "hedge_ratio": 0.5,
            "spot_shock_pct": 5.0,
            "bid_ask_pips": 2.0,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=30, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "pair",
                "spot",
                "exposure_notional",
                "hedge_notional",
                "residual_notional",
                "pnl_unhedged",
                "pnl_hedged",
                "hedge_cost",
                "as_of",
                "data_mode",
            ],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="metric", label="Metric", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.4f"),
                ColumnSpec(key="unit", label="Unit", kind="tag"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="hedge_notional", label="Hedge notional", kind="big_number"),
                CardSlot(key="residual_notional", label="Residual", kind="kpi"),
                CardSlot(key="pnl_unhedged", label="P/L unhedged", kind="trend_pill"),
                CardSlot(key="pnl_hedged", label="P/L hedged", kind="trend_pill"),
                CardSlot(key="hedge_cost", label="Hedge cost", kind="kpi"),
                CardSlot(key="hedge_ratio", label="Ratio", kind="badge"),
                CardSlot(key="tenor", label="Tenor", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FXH sizes an FX forward hedge against a foreign-currency "
            "exposure. Hedge notional = exposure_notional × hedge_ratio "
            "(opposite-sign of the exposure side). Residual = exposure × "
            "(1 - hedge_ratio). Under the user's spot shock the unhedged "
            "P/L (in base currency) is exposure × spot × shock_pct/100; the "
            "hedged P/L applies the same shock only to the residual notional. "
            "Hedge cost = hedge_notional × (bid_ask_pips / 10000), reported "
            "in base currency. The handler refuses to invent a spot value: "
            "if the live quote is unavailable, the calculation halts with a "
            "warning rather than silently using zero."
        ),
        formula_dict={
            "hedge_notional": Formula(
                expression=r"N_{hedge} = N_{exp} \times h",
                variables={"N_exp": "Exposure notional", "h": "Hedge ratio in [0, 1]"},
            ),
            "residual_notional": Formula(
                expression=r"N_{resid} = N_{exp} \times (1 - h)",
                variables={"N_exp": "Exposure notional", "h": "Hedge ratio"},
            ),
            "pnl_unhedged": Formula(
                expression=r"PnL_{unhedged} = N_{exp} \cdot S \cdot \frac{shock}{100}",
                variables={"S": "Spot", "shock": "Spot shock in %"},
                notes="Sign convention: positive when shock moves with exposure_side.",
            ),
            "pnl_hedged": Formula(
                expression=r"PnL_{hedged} = N_{resid} \cdot S \cdot \frac{shock}{100} - cost",
                variables={"cost": "Hedge cost"},
            ),
            "hedge_cost": Formula(
                expression=r"cost = N_{hedge} \cdot \frac{pips}{10^{4}}",
                variables={"pips": "Bid-ask in pips"},
            ),
        },
        field_dict={
            "pair": FieldDef(description="FX pair the exposure is denominated in.", source="input"),
            "spot": FieldDef(description="Spot rate used for sizing.", source="provider"),
            "exposure_notional": FieldDef(unit="foreign_ccy", description="Echoed exposure notional.", source="input"),
            "hedge_notional": FieldDef(unit="foreign_ccy", description="Notional locked in the hedge forward.", source="computed"),
            "residual_notional": FieldDef(unit="foreign_ccy", description="Unhedged residual exposure.", source="computed"),
            "pnl_unhedged": FieldDef(unit="base_ccy", description="P/L under the shock with no hedge.", source="computed"),
            "pnl_hedged": FieldDef(unit="base_ccy", description="P/L under the shock with the hedge.", source="computed"),
            "hedge_cost": FieldDef(unit="base_ccy", description="Estimated transaction cost.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fxh_full_hedge_zero_residual",
                description="hedge_ratio=1.0 leaves residual_notional = 0.",
                inputs={
                    "pair": "EURUSD",
                    "exposure_notional": 1_000_000,
                    "exposure_side": "long_foreign",
                    "hedge_ratio": 1.0,
                    "spot_shock_pct": 5.0,
                    "tenor": "3M",
                },
                assertions=[
                    "residual_notional_equals_zero",
                    "pnl_hedged_equals_negative_hedge_cost",
                ],
            ),
            SemanticTest(
                name="fxh_no_hedge_pnl_matches_unhedged",
                description="hedge_ratio=0.0 leaves pnl_hedged == pnl_unhedged and hedge_cost = 0.",
                inputs={
                    "pair": "EURUSD",
                    "exposure_notional": 1_000_000,
                    "hedge_ratio": 0.0,
                    "spot_shock_pct": 5.0,
                },
                assertions=[
                    "hedge_notional_equals_zero",
                    "hedge_cost_equals_zero",
                    "pnl_hedged_equals_pnl_unhedged",
                ],
            ),
            SemanticTest(
                name="fxh_no_silent_zero_spot",
                description="Without a spot value, FXH warns instead of using spot=0.",
                inputs={"pair": "EURUSD", "_mock": "spot_unavailable"},
                assertions=["calculation_halts_with_warning"],
            ),
        ],
    )


__all__ = ["fxh"]
