"""TRA — Total Return Analysis (TWR, IRR, CAGR, price return, drawdown).

Growth of one unit over the observed price history with dividends reinvested
(time-weighted), a money-weighted IRR, and the price-only return kept
separate. Live yfinance daily bars by default; reference=true serves the
labelled template history.

The per-fill broker ledger that used to sit under this code is not served
by any function and was removed from the catalog (TRA#4).
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
def tra() -> FunctionManifest:
    return FunctionManifest(
        code="TRA",
        name="Total Return Analysis",
        category=Category.PORTFOLIO,
        intent=(
            "Total return of one instrument over the observed history: "
            "time-weighted total return with dividends reinvested, money-weighted "
            "IRR, annualized CAGR, price return and max drawdown."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Instrument whose total return is measured.",
            ),
            InputSpec(
                name="years",
                label="Lookback (years)",
                control=ControlKind.NUMBER,
                required=False,
                description="Requested window. The CAGR uses the span actually observed.",
                min=1,
                max=30,
                step=1,
                unit="years",
            ),
            InputSpec(
                name="reference",
                label="Reference (template)",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Serve the labelled template history instead of live prices.",
            ),
        ],
        defaults={
            "years": 5,
            "reference": False,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=[],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=[
                "price_return_total",
                "twr_total",
                "irr_annualized",
                "cagr",
                "max_drawdown",
                "total_return_basis",
            ],
            rows=False,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.TIME_SERIES_LINE,
            x_axis=AxisSpec(type="time", unit="", label="Date"),
            y_axis=AxisSpec(type="numeric", unit="x", label="Growth of 1"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=None,
        card_schema=CardSchema(
            slots=[
                CardSlot(key="twr_total", label="TWR", kind="kpi", unit="%"),
                CardSlot(key="irr_annualized", label="IRR", kind="kpi", unit="%"),
                CardSlot(key="cagr", label="CAGR", kind="kpi", unit="%"),
                CardSlot(key="price_return_total", label="Price return", kind="kpi", unit="%"),
                CardSlot(key="max_drawdown", label="Max DD", kind="kpi", unit="%"),
                CardSlot(key="dividends_total", label="Dividends", kind="kpi", unit="ccy"),
            ],
        ),
        methodology=(
            "TRA fetches daily closes and cash dividends from yfinance for the requested "
            "window, or the labelled template history when reference=true or the live feed "
            "fails. TWR compounds daily total returns (C_t + D_t) / C_(t-1) with each dividend "
            "reinvested at the close of its ex-date. Price return is the last close over the "
            "first close minus one and excludes dividends. IRR is the money-weighted annualized "
            "return on a buy at the first close, the dividends received, and a sale at the last "
            "close. CAGR annualizes the total-return index over the observed span. Max drawdown "
            "is measured on the full daily total-return index. When the dividend series is "
            "unavailable, total_return_basis is price_only_dividends_unavailable and TWR and "
            "CAGR are price-based."
        ),
        formula_dict={
            "TWR": Formula(
                expression=r"TWR = \prod_t \frac{C_t + D_t}{C_{t-1}} - 1",
                variables={
                    "C_t": "Close on day t",
                    "D_t": "Cash dividend on day t (0 when none)",
                },
            ),
            "MaxDrawdown": Formula(
                expression=r"MDD = \min_t \left( I_t / \max_{s \le t} I_s - 1 \right)",
                variables={"I_t": "Total-return index, I_0 = 1"},
            ),
        },
        field_dict={
            "twr_total": FieldDef(unit="decimal", description="Time-weighted return; total return when total_return_basis is dividends_reinvested.", source="computed"),
            "irr_annualized": FieldDef(unit="decimal", description="Money-weighted annualized return from buy, dividend and sale cash flows.", source="computed"),
            "cagr": FieldDef(unit="decimal", description="Annualized growth over the observed span on the same basis as twr_total.", source="computed"),
            "price_return_total": FieldDef(unit="decimal", description="Last close over first close minus one; excludes dividends.", source="computed"),
            "max_drawdown": FieldDef(unit="decimal", description="Most negative peak-to-trough move of the daily total-return index (<= 0).", source="computed"),
            "dividends_total": FieldDef(unit="ccy", description="Sum of cash dividends in the window; null when the series is unavailable.", source="provider"),
            "total_return_basis": FieldDef(description="dividends_reinvested or price_only_dividends_unavailable.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="tra_twr_reinvests_dividends",
                description="With dividends known, TWR is at least the price return and the basis is labelled.",
                inputs={"symbol": "AAPL", "years": 5},
                assertions=[
                    "total_return_basis == 'dividends_reinvested'",
                    "twr_total >= price_return_total",
                ],
            ),
            SemanticTest(
                name="tra_missing_dividends_labelled_price_only",
                description="Template history has no dividend series: the basis says price-only and dividends_total is null.",
                inputs={"symbol": "AAPL", "reference": True},
                assertions=[
                    "total_return_basis == 'price_only_dividends_unavailable'",
                    "dividends_total is null",
                ],
            ),
            SemanticTest(
                name="tra_reference_never_claims_live",
                description="reference=true serves the labelled template and never reports live.",
                inputs={"symbol": "AAPL", "reference": True},
                assertions=["metadata.live is False"],
            ),
        ],
    )


__all__ = ["tra"]
