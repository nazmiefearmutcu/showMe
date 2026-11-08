"""GREEKS — Portfolio Greeks roll-up.

Aggregates contract-level Black-Scholes Greeks across an option book
supplied as JSON positions. Every row is scaled by quantity × contract
size; portfolio totals are the sums across positions, in trader-readable
units (vega per 1% vol move, theta per calendar day, rho per 1 bp move).
Resynced to the shipped params-driven handler
(``engine/functions/portfolio/greeks.py`` + ``services/greeks.py``) by
fix lane F14 — the previous seed described a broker credential_id flow
that was never implemented (flagged by fix lane F8).
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
def greeks() -> FunctionManifest:
    return FunctionManifest(
        code="GREEKS",
        name="Portfolio Greeks",
        category=Category.PORTFOLIO,
        intent=(
            "Sum delta / gamma / vega / theta / rho across an operator-supplied option "
            "book, where each contract's Greeks come from the internal Black-Scholes "
            "model scaled by quantity × contract size and reported in trader-readable "
            "units."
        ),
        asset_classes=[
            AssetClass.OPTION,
            AssetClass.EQUITY,
            AssetClass.FUTURE,
            AssetClass.CRYPTO,
        ],
        inputs=[
            InputSpec(
                name="positions",
                label="Option book",
                control=ControlKind.TEXT,
                required=True,
                description=(
                    "JSON array of contracts: {symbol, kind: call|put, strike, expiry "
                    "(ISO date) or T (years), quantity, and optionally spot, vol, r, q, "
                    "contract_size}. Missing spot/vol come from daily history, a missing "
                    "rate from FRED DGS3MO, a missing contract_size defaults to 100 and a "
                    "missing q to 0; each default is reported."
                ),
            ),
        ],
        defaults={
            "positions": [],
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=15, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "positions",
                "totals",
                "n",
                "units",
                "summary",
                "methodology",
                "field_dictionary",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="kind", label="Kind", kind="tag"),
                ColumnSpec(key="strike", label="Strike", kind="number", format="%.2f"),
                ColumnSpec(key="spot", label="Spot", kind="number", format="%.2f"),
                ColumnSpec(key="quantity", label="Qty", kind="number", format="%.4g"),
                ColumnSpec(key="contract_size", label="Mult", kind="number", format="%d"),
                ColumnSpec(key="delta", label="Δ", kind="number", format="%.2f"),
                ColumnSpec(key="gamma", label="Γ", kind="number", format="%.4f"),
                ColumnSpec(key="theta", label="Θ (1d)", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="vega", label="Vega", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="rho", label="Rho", kind="currency", unit="ccy", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="delta", label="Net Δ", kind="big_number"),
                CardSlot(key="gamma", label="Net Γ", kind="kpi"),
                CardSlot(key="theta", label="Θ / day", kind="kpi", unit="ccy"),
                CardSlot(key="vega", label="Net Vega", kind="kpi", unit="ccy"),
                CardSlot(key="rho", label="Net Rho", kind="kpi", unit="ccy"),
                CardSlot(key="n", label="Positions", kind="kpi"),
                CardSlot(key="status", label="Status", kind="badge"),
            ],
        ),
        methodology=(
            "GREEKS computes contract-level Black-Scholes Greeks internally (no broker "
            "Greeks feed) with European closed-form exercise; American early exercise is "
            "not modelled. Each position supplies kind, strike and an expiry (ISO date or "
            "T in years, required: a missing expiry is an input_error). Spot and vol may be "
            "omitted for symbols with daily history: spot is the last daily close and vol is "
            "30-day realized volatility (252-day annualized), labelled per row as "
            "spot_source / vol_source. A missing rate uses the live 3-month T-bill yield "
            "(FRED DGS3MO), labelled rate_source. A missing contract_size uses 100 and a "
            "missing dividend yield q uses 0; both are reported per row and in "
            "assumptions_used. Per-contract values are scaled by quantity × contract_size "
            "and the portfolio delta/gamma/vega/theta/rho are the sums across positions. "
            "Trader-readable units: vega per 1% vol move, theta per calendar day, rho per "
            "1 bp rate move, delta/gamma per 1.0 underlying move. A position that cannot "
            "be priced fails the whole book with status calc_error (no partial totals); "
            "a refused input such as a missing expiry is input_error. An empty positions list "
            "returns status=input_required with an empty positions array and zeroed "
            "totals; the handler never fabricates a book."
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
                notes="Reported per calendar day (annual Θ / 365).",
            ),
            "Vega": Formula(
                expression=r"\nu = S \sqrt{T} \phi(d_1)",
                variables={},
                notes="Reported per 1% vol move (Vega/100).",
            ),
            "Rho": Formula(
                expression=r"\rho = \pm K T e^{-rT} N(\pm d_2)",
                variables={},
                notes="Reported per 1 bp rate move (Rho/10000).",
            ),
            "Aggregation": Formula(
                expression=r"\Delta_{book} = \sum_i qty_i \cdot mult_i \cdot \Delta_i",
                variables={"qty_i": "Position quantity", "mult_i": "Contract size"},
            ),
        },
        field_dict={
            "positions[]": FieldDef(description="Per-contract Greeks row, scaled by quantity × contract size.", source="computed"),
            "totals.delta": FieldDef(description="Book delta per 1.0 underlying move.", source="aggregated"),
            "totals.gamma": FieldDef(description="Book gamma per 1.0 underlying move.", source="aggregated"),
            "totals.theta": FieldDef(unit="ccy", description="Book time decay per calendar day.", source="aggregated"),
            "totals.vega": FieldDef(unit="ccy", description="Book vega per 1% vol move.", source="aggregated"),
            "totals.rho": FieldDef(unit="ccy", description="Book rho per 1 bp rate move.", source="aggregated"),
            "units": FieldDef(description="Unit convention strings for every Greek.", source="computed"),
            "assumptions_used": FieldDef(description="Defaults applied per position (contract_size=100 and q=0 when not supplied), tagged with the symbol.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=False,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="greeks_empty_book_returns_list_not_scalar",
                description=(
                    "An empty positions list returns status=input_required with positions "
                    "as an ARRAY ([]) and n=0 — never a scalar 0 (regression for the pane "
                    "crash fixed in F8)."
                ),
                inputs={"positions": []},
                assertions=[
                    "positions_is_list",
                    "positions_empty",
                    "n_equals_0",
                    "totals_all_zero",
                    "status_equals_input_required",
                ],
            ),
            SemanticTest(
                name="greeks_non_list_positions_returns_input_error",
                description="A non-list positions payload returns status=input_error with next_actions instead of crashing.",
                inputs={"positions": 0},
                assertions=[
                    "status_equals_input_error",
                    "next_actions_non_empty",
                ],
            ),
            SemanticTest(
                name="greeks_short_call_delta_is_negative",
                description="A short call (quantity < 0) contributes negative book delta.",
                inputs={"positions": [{"kind": "call", "quantity": -1, "spot": 100, "strike": 105, "vol": 0.3, "T": 0.1}]},
                assertions=["totals_delta_lt_0"],
            ),
            SemanticTest(
                name="greeks_units_are_trader_readable",
                description=(
                    "Vega is per 1% vol move, theta per calendar day and rho per 1 bp — the "
                    "payload's `units` map states each convention."
                ),
                inputs={},
                assertions=[
                    "units_vega_per_1pct",
                    "units_theta_per_day",
                    "units_rho_per_bp",
                ],
            ),
            SemanticTest(
                name="greeks_missing_expiry_is_input_error",
                description="A position without an expiry is refused with input_error naming the expiry; no T is assumed.",
                inputs={"positions": [{"kind": "put", "spot": 100, "strike": 95, "quantity": 1, "vol": 0.3, "rate": 0.04}]},
                assertions=[
                    "status_equals_input_error",
                    "reason_mentions_expiry",
                    "next_actions_non_empty",
                ],
            ),
            SemanticTest(
                name="greeks_missing_multiplier_and_dividend_reported",
                description="A missing contract_size (100) and dividend yield q (0) are applied and reported in assumptions_used and per-row source fields, never silently.",
                inputs={"positions": [{"kind": "put", "symbol": "AAPL", "spot": 100, "strike": 95, "quantity": 1, "vol": 0.3, "T": 0.25, "rate": 0.04}]},
                assertions=[
                    "contract_size_source_is_default_100",
                    "q_source_is_default_0",
                    "assumptions_used_mentions_contract_size_and_q",
                ],
            ),
        ],
    )


__all__ = ["greeks"]
