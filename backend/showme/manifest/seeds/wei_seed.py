"""WEI — World equity indices ranker.

Bloomberg ``WEI<GO>`` analogue: live (or 30 s polled) snapshot for
~60 benchmark indices grouped by region. Rendered as a ranked bar
ladder (BAR_LADDER, not row-index series) so the operator can read
breadth at a glance. Backend handler is
``engine/functions/screening/wei.py`` which uses yfinance ^/index
tickers and supports region filtering plus per-row sparklines.
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
def wei() -> FunctionManifest:
    return FunctionManifest(
        code="WEI",
        name="World Equity Indices",
        category=Category.SCREENING,
        intent=(
            "Surface ~60 world equity benchmarks grouped by region with live or 30s polled snapshot "
            "of Δ/Δ%, intraday range, breadth, and a ranked bar ladder so the operator can read which "
            "markets are leading and lagging at a glance."
        ),
        asset_classes=[AssetClass.INDEX, AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="region",
                label="Region",
                control=ControlKind.SELECT,
                required=True,
                description="Region filter.",
                options=["all", "americas", "europe", "asia", "mea"],
            ),
            InputSpec(
                name="sort_by",
                label="Sort",
                control=ControlKind.SELECT,
                required=True,
                description="Sort key for the ranked ladder.",
                options=["change_pct_desc", "change_pct_asc", "alpha", "region"],
            ),
            InputSpec(
                name="show_sparklines",
                label="Sparklines",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Render an inline sparkline per row.",
            ),
            InputSpec(
                name="poll_seconds",
                label="Poll (s)",
                control=ControlKind.NUMBER,
                required=False,
                description="Refresh interval; pane pauses on hidden tabs.",
                min=5,
                max=300,
                step=5,
                unit="s",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; provider may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "region": "all",
            "sort_by": "change_pct_desc",
            "show_sparklines": True,
            "poll_seconds": 30,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=30, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "region", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        # WEI is the canonical bar-ladder exemplar: each index gets a ranked
        # horizontal bar centered on zero with positive/negative tones. NOT
        # a time-series line — that would be GP, not WEI.
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="%", label="Δ%"),
            y_axis=AxisSpec(type="category", unit="", label="Index"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Index", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="region", label="Region", kind="tag"),
                ColumnSpec(key="last", label="Last", kind="number", format="%.2f"),
                ColumnSpec(key="change", label="Δ", kind="number", format="%.2f"),
                ColumnSpec(key="change_pct", label="Δ %", kind="percent", format="%.2f"),
                ColumnSpec(key="low", label="Low", kind="number", format="%.2f"),
                ColumnSpec(key="high", label="High", kind="number", format="%.2f"),
                ColumnSpec(key="market_state", label="State", kind="tag"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="count", label="Indices", kind="kpi"),
                CardSlot(key="aggregate_change_pct", label="Aggregate Δ", kind="trend_pill", unit="%"),
                CardSlot(key="advancers", label="Up", kind="kpi"),
                CardSlot(key="decliners", label="Down", kind="kpi"),
                CardSlot(key="leader", label="Leader", kind="badge"),
                CardSlot(key="laggard", label="Laggard", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "WEI iterates a curated ~60-index ticker list grouped by region: Americas (^GSPC, ^IXIC, "
            "^DJI, ^GSPTSE, ^MERV, ^BVSP, …), Europe (^FTSE, ^GDAXI, ^FCHI, ^STOXX50E, ^IBEX, ^AEX, "
            "^OMX, …), Asia (^N225, ^HSI, ^KS11, ^TWII, ^BSESN, ^AXJO, …), MEA (^TA125, ^TASI, ^EGX30, "
            "^JN0U, …). For each it pulls last/change/change_pct/low/high from yfinance with a 30s "
            "cache and a poll loop paused on hidden tabs. Aggregate breadth = (advancers / count); "
            "weighted aggregate Δ = arithmetic mean of change_pct over rows with a finite Δ. Rows "
            "with no Δ are surfaced as warnings rather than counted as flat. Visualization is a "
            "ranked horizontal bar ladder centered on 0 (NOT a row-index line). Next actions: "
            "open_in_gp on any row, save_screen for the region filter, export_csv."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Yahoo index ticker (^GSPC, ^N225, …).", source="curated"),
            "rows[].name": FieldDef(description="Display name.", source="curated"),
            "rows[].region": FieldDef(description="Region grouping tag.", source="curated"),
            "rows[].last": FieldDef(description="Last value.", source="yfinance"),
            "rows[].change": FieldDef(description="last - prev_close.", source="computed"),
            "rows[].change_pct": FieldDef(unit="%", description="change / prev_close * 100.", source="computed"),
            "rows[].low": FieldDef(description="Session low.", source="yfinance"),
            "rows[].high": FieldDef(description="Session high.", source="yfinance"),
            "rows[].market_state": FieldDef(description="regular / closed / pre / post.", source="yfinance"),
            "rows[].history": FieldDef(description="Intraday sparkline values.", source="yfinance_history"),
            "aggregate_change_pct": FieldDef(unit="%", description="Mean of finite per-row change_pct.", source="computed"),
            "advancers": FieldDef(unit="count", description="Rows with change_pct > 0.", source="computed"),
            "decliners": FieldDef(unit="count", description="Rows with change_pct < 0.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="wei_chart_grammar_is_bar_ladder",
                description="WEI manifest pins chart_grammar.kind to bar_ladder (ranked horizontal bars, not a row-index line).",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'bar_ladder'"],
            ),
            SemanticTest(
                name="wei_region_filter_restricts_rows",
                description="With region=europe every row's region equals 'europe'.",
                inputs={"region": "europe"},
                assertions=["all_rows_region_equals_europe"],
            ),
            SemanticTest(
                name="wei_sort_change_pct_desc_is_monotonic",
                description="With sort_by=change_pct_desc rows are monotonically non-increasing in change_pct.",
                inputs={"sort_by": "change_pct_desc"},
                assertions=["rows_monotonically_non_increasing_in_change_pct"],
            ),
            SemanticTest(
                name="wei_breadth_kpis_sum_to_count_or_less",
                description="advancers + decliners <= count (the remainder are flat or missing Δ).",
                inputs={},
                assertions=["advancers_plus_decliners_le_count"],
            ),
            SemanticTest(
                name="wei_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="wei_provider_unavailable_returns_warning_not_synthetic_zeros",
                description="When yfinance is down, rows that fail return Δ=null with a warning; aggregate is over finite rows only.",
                inputs={},
                assertions=[
                    "missing_row_change_pct_is_null_not_zero",
                    "warning_emitted_for_failed_rows",
                    "aggregate_over_finite_rows_only",
                ],
            ),
        ],
    )


__all__ = ["wei"]
