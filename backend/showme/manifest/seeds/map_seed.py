"""MAP — World market heatmap (major country equity-index ETFs).

Bloomberg ``MAP<GO>`` analogue over a curated set of single-country ETFs
(SPY, VGK, EWG, …): each tile is colored by the delivered change and
sized by |% change| magnitude (NOT market cap — the pane states this
explicitly). Live mode quotes each ETF and computes the intraday change
from last vs previous close; model mode returns a deterministic, labelled
country ETF template. ``chart_grammar.kind=HEATMAP`` per the wave2 spec
and pinned by ``test_map_chart_grammar_is_heatmap``. UI hangs off the
shared MarketHeatmapPane (same component as SECT).
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
def market_map() -> FunctionManifest:
    return FunctionManifest(
        code="MAP",
        name="World Market Heatmap",
        category=Category.SCREENING,
        intent=(
            "Render a heat grid of major country equity-index ETFs (US/EU/DE/GB/JP/CN/IN/BR …) "
            "colored by the delivered day change and sized by |% change| magnitude so an operator "
            "can read global market breadth in one glance. Live mode uses quote-provider intraday "
            "changes; model mode returns a deterministic, labelled country template — never a "
            "fabricated live print."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="live",
                label="Live quotes",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "True = quote-provider country ETF changes (default); False = explicitly "
                    "labelled deterministic country model."
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
        # Heat grid keyed by country — pinned kind=HEATMAP per the wave2
        # chart-grammar contract.
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="category", unit="", label="Country"),
            y_axis=AxisSpec(type="numeric", unit="%", label="Change"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="country", label="Country", kind="text"),
                ColumnSpec(key="etf", label="ETF", kind="tag"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.2f"),
                ColumnSpec(key="change_pct", label="Δ %", kind="percent", format="%.2f"),
                ColumnSpec(key="period", label="Period", kind="tag"),
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
                CardSlot(key="period", label="Window", kind="badge"),
                CardSlot(key="quote_type", label="Source", kind="mode_pill"),
            ],
        ),
        methodology=(
            "MAP quotes a curated map of single-country equity-index ETFs (SPY/VGK/EWG/EWU/EWQ/"
            "EWI/EWP/EWJ/FXI/INDA/EWZ/EWW/TUR/EZA/EWA/EWC/EWY/EWT/EWH/EIDO/KSA/ARGT/VNM/EPOL/RSX). "
            "For each ETF the intraday change_pct = last / previous_close - 1 (null when either "
            "leg is missing — never a phantom -100% drop). Rows carry quote_type='live' when the "
            "quote provider answered, 'unavailable' when a single ETF failed, and 'model' in the "
            "deterministic fallback branch, which also sets status='model' (or "
            "status='provider_unavailable' with a reason + next_actions when no live row was "
            "usable). The pane colours tiles by the delivered change, sizes them by |% change| "
            "magnitude (NOT market cap), shows a MODEL banner for fallback data and renders a "
            "missing change as an explicit em-dash — never 0.00%."
        ),
        field_dict={
            "rows[].country": FieldDef(description="ISO-style country key.", source="curated"),
            "rows[].etf": FieldDef(description="Country equity-index ETF ticker (SPY, VGK, …).", source="curated"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Latest quoted ETF price.", source="yfinance"),
            "rows[].change_pct": FieldDef(unit="%", description="Intraday change (last vs previous close); null when unavailable.", source="computed"),
            "rows[].period": FieldDef(description="Period the change covers (intraday 1D).", source="computed"),
            "rows[].quote_type": FieldDef(description="live | unavailable | model provenance flag.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="map_chart_grammar_is_heatmap",
                description="MAP manifest pins chart_grammar.kind to heatmap (country heat grid).",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'heatmap'"],
            ),
            SemanticTest(
                name="map_model_fallback_is_labelled_not_live",
                description="Model mode / all-quotes-failed rows carry quote_type='model' (or status model/provider_unavailable) and never claim a live print.",
                inputs={"live": False},
                assertions=[
                    "rows_quote_type_model",
                    "status_in_model_or_provider_unavailable",
                ],
            ),
            SemanticTest(
                name="map_missing_change_is_null_not_zero",
                description="A failed country ETF quote surfaces change_pct=null (rendered '—'), never a fabricated 0.00% flat move.",
                inputs={},
                assertions=["missing_change_pct_is_null_not_zero"],
            ),
        ],
    )


__all__ = ["market_map"]
