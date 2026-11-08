"""SECT — Sector heatmap (S&P 500 sector ETF performance).

Bloomberg ``SECT<GO>`` analogue: the eleven SPDR sector ETFs rendered as a
ranked heat grid colored by the delivered change, with 1D/MTD/QTD/YTD
window controls and an explicit live-vs-model source mode. UI hangs off
the shared MarketHeatmapPane (same component as MAP). Live 1D changes
come from the quote's previous close; MTD/QTD/YTD changes are the live
last price against the last daily close before the window opens. A
window whose base close is missing yields a null change and a warning —
the pane labels every change value with the delivered period. ``chart_grammar.kind`` stays BAR_LADDER per the wave-2 contract
(ranked sector return ladder over the same rows).
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
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def sect() -> FunctionManifest:
    return FunctionManifest(
        code="SECT",
        name="Sector Heatmap",
        category=Category.SCREENING,
        intent=(
            "Rank the eleven S&P 500 sector ETFs (XLK, XLF, XLE, XLV, XLI, XLP, XLY, XLU, XLB, "
            "XLRE, XLC) by performance over the selected 1D/MTD/QTD/YTD window so an operator can "
            "read sector rotation at a glance. Live mode computes each window from quotes and daily "
            "history and discloses any window it cannot compute; model mode lists the sectors with "
            "no price or change values — never a fabricated print."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="period",
                label="Window",
                control=ControlKind.SELECT,
                required=False,
                description="Performance window: 1D quote change, or MTD/QTD/YTD from daily closes.",
                options=["1D", "MTD", "QTD", "YTD"],
            ),
            InputSpec(
                name="live",
                label="Live quotes",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "True = quote-provider sector ETF changes (default); False = explicitly "
                    "labelled deterministic sector model."
                ),
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; provider may downgrade and report it.",
                options=[
                    DataMode.LIVE_EXCHANGE.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.MODELED.value,
                ],
            ),
        ],
        defaults={
            "period": "1D",
            "live": True,
            "provider_mode": DataMode.LIVE_EXCHANGE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot", "internal"],
            acceptable_modes=[
                DataMode.LIVE_EXCHANGE,
                DataMode.DELAYED_REFERENCE,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["rows", "period"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        # Ranked sector ladder — the pane renders the heat grid plus a
        # best/worst legend rail over these same rows.
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="%", label="Change"),
            y_axis=AxisSpec(type="category", unit="", label="Sector"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="sector", label="Sector", kind="text"),
                ColumnSpec(key="etf", label="ETF", kind="tag"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.2f"),
                ColumnSpec(key="change_pct", label="Change", kind="percent", format="%.2f"),
                ColumnSpec(key="change_pct_period", label="Δ period", kind="tag"),
                ColumnSpec(key="period", label="Requested", kind="tag"),
                ColumnSpec(key="quote_type", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="best", label="Best", kind="trend_pill", unit="%"),
                CardSlot(key="worst", label="Worst", kind="trend_pill", unit="%"),
                CardSlot(key="breadth", label="Breadth", kind="kpi"),
                CardSlot(key="change_pct_period", label="Delivered", kind="badge"),
                CardSlot(key="quote_type", label="Source", kind="mode_pill"),
            ],
        ),
        methodology=(
            "SECT maps the canonical GICS sector set to its SPDR sector ETF (XLK, XLF, XLE, XLV, "
            "XLI, XLP, XLY, XLU, XLB, XLRE, XLC). In live mode each ETF is quoted through the "
            "provider. For 1D, change_pct is last vs previous close. For MTD/QTD/YTD it is last vs "
            "the last daily close on or before the prior month-, quarter- or year-end; the handler "
            "stamps change_pct_period with the window it computed, and a row whose base close is "
            "missing keeps a null change plus a warning. In model mode (or when every live quote "
            "fails) rows carry quote_type='model' and no price or change values, with status='model' "
            "or 'provider_unavailable', and the pane shows a prominent MODEL banner. Rows are ranked by change_pct and the pane derives "
            "breadth and best/worst from finite changes only — a missing change renders as an "
            "explicit em-dash, never 0.00%."
        ),
        field_dict={
            "rows[].sector": FieldDef(description="GICS sector name.", source="curated"),
            "rows[].etf": FieldDef(description="SPDR sector ETF ticker (XLK, XLF, …).", source="curated"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Latest quoted ETF price.", source="yfinance"),
            "rows[].change_pct": FieldDef(unit="%", description="Change over the delivered period; null when unavailable.", source="yfinance"),
            "rows[].change_pct_period": FieldDef(description="Window the change covers (1D, MTD, QTD or YTD); null when no change.", source="computed"),
            "rows[].period": FieldDef(description="Window the caller requested.", source="config"),
            "rows[].quote_type": FieldDef(description="live | model | unavailable provenance flag.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="sect_chart_grammar_is_bar_ladder",
                description="SECT manifest pins chart_grammar.kind to bar_ladder (ranked sector change ladder).",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'bar_ladder'"],
            ),
            SemanticTest(
                name="sect_live_period_mismatch_is_disclosed",
                description=(
                    "When a requested window's base close is missing for some sector ETFs, those rows "
                    "carry a null change and the payload warns naming the window — the change is never "
                    "relabelled as another window."
                ),
                inputs={"period": "MTD", "live": True},
                assertions=[
                    "rows_missing_base_have_null_change_pct",
                    "warning_mentions_requested_period",
                ],
            ),
            SemanticTest(
                name="sect_model_fallback_is_labelled_not_live",
                description="Model mode / all-quotes-failed rows carry quote_type='model' (or status model/provider_unavailable), no price or change values, and never claim a live print.",
                inputs={"live": False},
                assertions=[
                    "rows_quote_type_model",
                    "status_in_model_or_provider_unavailable",
                ],
            ),
            SemanticTest(
                name="sect_missing_change_is_null_not_zero",
                description="A failed live ETF quote surfaces change_pct=null (rendered '—'), never a fabricated 0.00% flat move.",
                inputs={},
                assertions=["missing_change_pct_is_null_not_zero"],
            ),
        ],
    )


__all__ = ["sect"]
