"""MGN — Cross-account margin model.

Estimates initial margin, maintenance margin and buying power per account with
ShowMe's own margin model (margin_engine: Reg-T, portfolio-stress, crypto spot /
futures, futures per-contract and FX rule tables). The numbers are model estimates
from the positions the caller supplies, or from the saved portfolio marked to live
quotes. They are NOT read from a broker: no broker account or margin call is
queried, and borrow, liquidation and margin-call diagnostics are not produced.
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
        name="Margin Model",
        category=Category.PORTFOLIO,
        intent=(
            "Per-account margin estimate: initial margin, maintenance margin, "
            "excess initial equity and buying power, computed by ShowMe's margin "
            "model from the positions. A model estimate, not a broker margin figure."
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
                name="cash",
                label="Cash",
                control=ControlKind.NUMBER,
                required=False,
                description="Cash for the account named by account (or the only account in the book). Applies to this calculation only and is not saved.",
            ),
            InputSpec(
                name="account",
                label="Account",
                control=ControlKind.TEXT,
                required=False,
                description="Account the cash belongs to. Optional when the saved book has one account; required when it has several.",
            ),
            InputSpec(
                name="margin_type",
                label="Margin model",
                control=ControlKind.SELECT,
                required=False,
                description="Account margin model; omitted means inferred from the book.",
                options=["reg_t", "portfolio", "crypto_spot", "crypto_futures", "futures", "fx", "bond"],
            ),
            InputSpec(
                name="refresh_prices",
                label="Live marks",
                control=ControlKind.SELECT,
                required=False,
                description="Mark saved-portfolio positions to live quotes (default true). Unquoted positions stay at average cost and are flagged.",
                options=["true", "false"],
            ),
        ],
        defaults={
            "refresh_prices": True,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["yfinance"],
            acceptable_modes=[
                DataMode.MODELED,
                DataMode.DELAYED_REFERENCE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=10, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=[
                "accounts",
                "rows",
                "total",
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
                ColumnSpec(key="account", label="Account", kind="text"),
                ColumnSpec(key="margin_type", label="Model", kind="text"),
                ColumnSpec(key="market_value", label="Mkt value", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="initial_margin", label="Initial", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="maintenance_margin", label="Maint.", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="buying_power", label="Buying power", kind="currency", unit="ccy", format="%.2f"),
                ColumnSpec(key="maintenance_cushion_pct", label="Cushion %", kind="percent", unit="%", format="%.2f"),
                ColumnSpec(key="positions", label="Positions", kind="number", format="%d"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="buying_power", label="Buying power", kind="big_number", unit="ccy"),
                CardSlot(key="excess_initial", label="Excess initial", kind="kpi", unit="ccy"),
                CardSlot(key="initial_margin", label="Initial", kind="kpi", unit="ccy"),
                CardSlot(key="maintenance_margin", label="Maintenance", kind="kpi", unit="ccy"),
                CardSlot(key="maintenance_cushion_pct", label="Cushion %", kind="kpi", unit="%"),
            ],
        ),
        methodology=(
            "MGN groups the positions by account and marks each one at its supplied price or "
            "its live quote; a position with no quote stays at average cost and is listed as "
            "marked at cost. ShowMe's margin model then applies the account's rule to each "
            "position: initial and maintenance margin are rates of notional (or fixed per "
            "contract for futures). Buying power is the equity surplus over initial margin "
            "divided by the initial rate, or times PORTFOLIO_BUYING_POWER_MULTIPLE (4) for a "
            "portfolio-margin account, whose maintenance is scaled by PORTFOLIO_MAINTENANCE_SCALE "
            "(0.6). These are model assumptions, not broker-published requirements. Equity is "
            "cash plus market value. Cash is, in order: the cash stated for the account in the "
            "request (cash with account, for this calculation only); the account's recorded cash; "
            "or, for a single-account book with no recorded account, the book's recorded USD cash "
            "(PORT). An account with no cash on record counts as 0 and is flagged as cash not recorded."
        ),
        formula_dict={
            "ExcessInitial": Formula(
                expression=r"excess\_initial = equity - initial\_margin",
                variables={"equity": "Cash plus market value of the account"},
            ),
            "MaintenanceCushion": Formula(
                expression=r"cushion\_pct = (equity - maintenance\_margin) / equity \times 100",
                variables={},
                notes="Model-based: uses the modeled maintenance requirement.",
            ),
        },
        field_dict={
            "initial_margin": FieldDef(unit="ccy", description="Modeled initial margin requirement.", source="margin_engine"),
            "maintenance_margin": FieldDef(unit="ccy", description="Modeled maintenance margin requirement.", source="margin_engine"),
            "excess_initial": FieldDef(unit="ccy", description="equity - modeled initial margin.", source="computed_from_model"),
            "buying_power": FieldDef(unit="ccy", description="Modeled capacity for additional notional under the account rule.", source="computed_from_model"),
            "maintenance_cushion_pct": FieldDef(unit="%", description="Cushion above the modeled maintenance requirement.", source="computed_from_model"),
            "rows[].source": FieldDef(description="Always the margin model; never a broker figure.", source="margin_engine"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=False,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "maintenance_cushion_below",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="mgn_numbers_are_model_estimates_not_broker_figures",
                description=(
                    "Margin fields are produced by the ShowMe margin model; no broker "
                    "margin source is claimed."
                ),
                inputs={"positions": "[]"},
                assertions=[
                    "sources does not contain a broker source",
                    "accounts[].margin_type is one of the model rule names",
                ],
            ),
            SemanticTest(
                name="mgn_excess_initial_equals_equity_minus_initial_margin",
                description="Excess initial equity is exact from the modeled inputs.",
                inputs={"positions": "[{\"symbol\":\"AAPL\",\"asset_class\":\"EQUITY\",\"quantity\":10,\"avg_cost\":100,\"last\":110}]"},
                assertions=["accounts[].excess_initial == accounts[].equity - accounts[].initial_margin"],
            ),
            SemanticTest(
                name="mgn_unquoted_position_is_disclosed_at_cost",
                description="A position with no quote is marked at average cost and disclosed; the metadata is flagged degraded.",
                inputs={"positions": "[{\"symbol\":\"MSFT\",\"asset_class\":\"EQUITY\",\"quantity\":5,\"avg_cost\":300}]"},
                assertions=[
                    "metadata.marked_at_cost contains MSFT",
                    "metadata.degraded == true",
                ],
            ),
            SemanticTest(
                name="mgn_empty_book_is_honest_empty_state",
                description="With no positions and no saved portfolio, MGN returns status empty, not zeros.",
                inputs={"positions": "[]"},
                assertions=["status == 'empty'", "next_actions is non-empty"],
            ),
        ],
    )


__all__ = ["mgn"]
