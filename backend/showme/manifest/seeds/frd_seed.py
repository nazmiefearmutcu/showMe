"""FRD — FX Forwards (covered interest parity).

Computes the no-arbitrage forward FX rate from spot plus domestic and
foreign interest rates via covered interest parity (CIP). Returns the
forward rate, the forward point quotation, and the implied carry for
the chosen tenor.
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
def frd() -> FunctionManifest:
    return FunctionManifest(
        code="FRD",
        name="FX Forwards (CIP)",
        category=Category.FX,
        intent=(
            "Compute the no-arbitrage FX forward via covered interest "
            "parity: F = S × (1 + r_quote × T) / (1 + r_base × T). Returns "
            "forward rate, forward points, and the implied carry — with "
            "the CIP formula visible in the formula dictionary."
        ),
        asset_classes=[AssetClass.FX, AssetClass.RATE],
        inputs=[
            InputSpec(
                name="base",
                label="Base currency",
                control=ControlKind.SELECT,
                required=True,
                description="Base currency of the pair (priced as quote currency per one unit of base).",
                options=["USD", "EUR", "GBP", "JPY", "TRY", "CHF", "AUD", "CAD"],
            ),
            InputSpec(
                name="quote",
                label="Quote currency",
                control=ControlKind.SELECT,
                required=True,
                description="Quote (pricing) currency of the pair.",
                options=["USD", "EUR", "GBP", "JPY", "TRY", "CHF", "AUD", "CAD"],
            ),
            InputSpec(
                name="tenor",
                label="Tenor",
                control=ControlKind.HORIZON,
                required=True,
                description="Forward tenor.",
                options=["1W", "1M", "3M", "6M", "1Y"],
            ),
            InputSpec(
                name="r_quote",
                label="Rate (quote currency)",
                control=ControlKind.NUMBER,
                required=False,
                description=(
                    "Annualized decimal rate for the quote (pricing) currency. "
                    "Blank uses the labelled reference rate for that currency."
                ),
                min=-0.05,
                max=0.50,
                step=0.0001,
                unit="decimal",
            ),
            InputSpec(
                name="r_base",
                label="Rate (base currency)",
                control=ControlKind.NUMBER,
                required=False,
                description=(
                    "Annualized decimal rate for the base currency. "
                    "Blank uses the labelled reference rate for that currency."
                ),
                min=-0.05,
                max=0.50,
                step=0.0001,
                unit="decimal",
            ),
            InputSpec(
                name="spot",
                label="Spot override",
                control=ControlKind.NUMBER,
                required=False,
                description="Optional manual spot (quote per base); otherwise live from yfinance.",
                min=0.0,
                step=0.0001,
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
            "base": "EUR",
            "quote": "USD",
            "tenor": "3M",
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
                "tenor",
                "forward_rate",
                "forward_points",
                "implied_carry",
                "as_of",
                "data_mode",
            ],
            rows=False,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        chart_grammar=None,
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="metric", label="Metric", kind="text"),
                ColumnSpec(key="value", label="Value", kind="number", format="%.6f"),
                ColumnSpec(key="unit", label="Unit", kind="tag"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="forward_rate", label="Forward", kind="big_number"),
                CardSlot(key="spot", label="Spot", kind="big_number"),
                CardSlot(key="forward_points", label="Forward pts", kind="kpi"),
                CardSlot(key="implied_carry", label="Implied carry", kind="trend_pill", unit="%"),
                CardSlot(key="tenor", label="Tenor", kind="badge"),
                CardSlot(key="r_quote", label="r quote", kind="badge", unit="decimal"),
                CardSlot(key="r_base", label="r base", kind="badge", unit="decimal"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FRD prices the FX forward via covered interest parity. Spot is "
            "fetched from yfinance for the BASE/QUOTE pair, or taken from the "
            "spot input when supplied. Tenor labels map to a year fraction T "
            "(xD = x/365, xW = 7x/365, xM = x/12, xY = x). The forward rate is "
            "F = S × (1 + r_quote × T') / (1 + r_base × T') where r_quote is the "
            "quote-currency (pricing currency) annualized rate and r_base is the "
            "base-currency annualized rate. Rates are decimals; a rate left blank "
            "uses the labelled reference rate for that currency. Both are "
            "simple-interest ACT/360 rates, so T' = T × 365/360 (calendar days / "
            "360). Forward points are the price difference (F - S) in quote "
            "currency per base currency. Implied carry is annualized "
            "(F/S - 1) / T × 100. The card row exposes r_quote, r_base, tenor, "
            "and spot source so users can audit the price."
        ),
        formula_dict={
            "covered_interest_parity": Formula(
                expression=r"F = S \cdot \frac{1 + r_{quote} \cdot T'}{1 + r_{base} \cdot T'}",
                variables={
                    "S": "Spot, quote currency per one base currency",
                    "r_quote": "Quote (pricing) currency annualized rate",
                    "r_base": "Base currency annualized rate",
                    "T'": "Tenor year fraction on the rate basis: T' = T × 365/360 (ACT/360)",
                },
                notes="Simple-interest CIP; the continuous-comp form is F = S × exp((r_quote - r_base) × T).",
            ),
            "forward_points": Formula(
                expression=r"pts = F - S",
                variables={"F": "Forward rate", "S": "Spot"},
                notes="Price difference in quote currency per base currency (not pips).",
            ),
            "implied_carry": Formula(
                expression=r"carry = \frac{F/S - 1}{T} \times 100",
                variables={"F": "Forward rate", "S": "Spot", "T": "Year fraction"},
                notes="Annualized implied carry in percent.",
            ),
        },
        field_dict={
            "pair": FieldDef(description="BASE+QUOTE (e.g. EURUSD).", source="computed"),
            "spot": FieldDef(description="Spot rate used in the CIP equation.", source="provider"),
            "tenor": FieldDef(description="Forward tenor label.", source="input"),
            "forward_rate": FieldDef(description="No-arbitrage forward from CIP.", source="computed"),
            "forward_points": FieldDef(unit="price", description="F - S, quote currency per base currency.", source="computed"),
            "implied_carry": FieldDef(unit="%", description="(F/S - 1) / T × 100.", source="computed"),
            "r_quote": FieldDef(unit="decimal", description="Quote (pricing) currency rate used (echoed; reference rate when not supplied).", source="input"),
            "r_base": FieldDef(unit="decimal", description="Base currency rate used (echoed; reference rate when not supplied).", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="frd_formula_dict_includes_cip",
                description="FRD must declare the covered_interest_parity formula explicitly.",
                inputs={},
                assertions=["formula_dict_contains_covered_interest_parity"],
            ),
            SemanticTest(
                name="frd_eurusd_3m_matches_cip_within_tolerance",
                description=(
                    "For known spot/r_quote/r_base, the returned forward rate "
                    "matches S × (1 + r_quote T') / (1 + r_base T') with T' = T × 365/360 "
                    "(ACT/360) within 1e-9."
                ),
                inputs={
                    "base": "EUR",
                    "quote": "USD",
                    "tenor": "3M",
                    "r_quote": 0.035,
                    "r_base": 0.045,
                    "spot": 1.0800,
                },
                assertions=[
                    "forward_rate_matches_cip_within_1e-9",
                    "forward_points_signed_correctly",
                    "implied_carry_signed_correctly",
                ],
            ),
            SemanticTest(
                name="frd_no_silent_zero_forward_when_spot_missing",
                description="Without a spot value, FRD warns instead of returning forward_rate=0.",
                inputs={"base": "EUR", "quote": "USD", "_mock": "spot_unavailable"},
                assertions=["forward_rate_absent_with_warning"],
            ),
        ],
    )


__all__ = ["frd"]
