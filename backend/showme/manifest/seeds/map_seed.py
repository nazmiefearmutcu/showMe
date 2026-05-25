"""MAP — Sector / country market map (treemap).

Bloomberg ``MAP<GO>`` analogue: a treemap of the equity universe
where each tile is sized by market cap and colored by daily change.
Treemap is conceptually a heatmap (color-coded grid keyed by
category), so chart_grammar.kind=HEATMAP per the wave2 spec.
Backend handler is ``engine/functions/screening/market_map.py``.
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
        name="Market Heatmap",
        category=Category.SCREENING,
        intent=(
            "Render a treemap of the chosen universe with tiles sized by market cap and colored by "
            "daily change, grouped by sector or country, so an operator can read sector rotation and "
            "concentration risk in one glance."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.SELECT,
                required=True,
                description="Universe to map.",
                options=["SP500", "NDX", "DJIA", "RUSSELL2000", "STOXX600"],
            ),
            InputSpec(
                name="group_by",
                label="Group by",
                control=ControlKind.SELECT,
                required=True,
                description="Top-level grouping (sector or country).",
                options=["sector", "country", "industry"],
            ),
            InputSpec(
                name="size_metric",
                label="Tile size",
                control=ControlKind.SELECT,
                required=True,
                description="Metric driving tile area.",
                options=["market_cap", "dollar_volume", "free_float_cap"],
            ),
            InputSpec(
                name="color_metric",
                label="Tile color",
                control=ControlKind.SELECT,
                required=True,
                description="Metric driving tile color.",
                options=["change_pct_1d", "change_pct_5d", "change_pct_1m", "ytd"],
            ),
            InputSpec(
                name="period",
                label="Period",
                control=ControlKind.SELECT,
                required=False,
                description="Period the change metric covers.",
                options=["1D", "MTD", "QTD", "YTD"],
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
            "universe": "SP500",
            "group_by": "sector",
            "size_metric": "market_cap",
            "color_metric": "change_pct_1d",
            "period": "1D",
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
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "groups", "size_metric", "color_metric", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        # Treemap is conceptually a heatmap — color-coded grid keyed by
        # category. We pin kind=HEATMAP per the wave2 chart-grammar contract.
        chart_grammar=ChartGrammar(
            kind=ChartKind.HEATMAP,
            x_axis=AxisSpec(type="category", unit="", label="Group"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="group", label="Group", kind="tag"),
                ColumnSpec(key="size_value", label="Size", kind="currency", format="si"),
                ColumnSpec(key="color_value", label="Δ %", kind="percent", format="%.2f"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.2f"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_tiles", label="Tiles", kind="kpi"),
                CardSlot(key="groups_count", label="Groups", kind="kpi"),
                CardSlot(key="top_group_change", label="Top Group Δ", kind="trend_pill", unit="%"),
                CardSlot(key="bottom_group_change", label="Bot. Group Δ", kind="trend_pill", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MAP enumerates the selected universe's constituent tickers (SP500/NDX/RUSSELL2000 from "
            "bundled JSON, STOXX600 from a cached pull). For each row it pulls the size metric "
            "(market_cap by default) and the color metric (change_pct_1d by default) from yfinance "
            "with a 2-min DuckDB cache. Rows are grouped by group_by (sector/country/industry) and "
            "the renderer paints a squarified treemap where each tile area is proportional to "
            "size_metric and each tile color is interpolated on a diverging scale (deep red -1 → "
            "white 0 → deep green +1) by color_metric. Tiles missing data are surfaced as warnings "
            "rather than painted gray-with-0. Treemap is conceptually a heatmap — chart_grammar.kind "
            "is HEATMAP per the wave2 contract. Next actions: drill_into_group, open_in_gp, "
            "save_screen, export_csv."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Constituent ticker.", source="universe"),
            "rows[].name": FieldDef(description="Issuer name.", source="yfinance"),
            "rows[].group": FieldDef(description="Sector / country / industry tag.", source="yfinance"),
            "rows[].size_value": FieldDef(unit="USD", description="Value driving tile area (market_cap or dollar_volume).", source="yfinance"),
            "rows[].color_value": FieldDef(unit="%", description="Value driving tile color (change_pct).", source="yfinance"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Last trade price.", source="yfinance"),
            "groups[].name": FieldDef(description="Group label.", source="derived"),
            "groups[].weight": FieldDef(unit="%", description="Group share of total size_metric.", source="computed"),
            "groups[].weighted_change_pct": FieldDef(unit="%", description="Cap-weighted change for the group.", source="computed"),
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
                description="MAP manifest pins chart_grammar.kind to heatmap (treemap is conceptually a heatmap).",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'heatmap'"],
            ),
            SemanticTest(
                name="map_group_by_sector_yields_known_group_set",
                description="With group_by=sector groups[] is a subset of canonical GICS sectors.",
                inputs={"group_by": "sector"},
                assertions=["all_groups_in_gics_sector_set"],
            ),
            SemanticTest(
                name="map_tile_size_proportional_to_size_metric",
                description="For two rows A and B in the same group, A.size_value >= B.size_value implies tile_area(A) >= tile_area(B).",
                inputs={"size_metric": "market_cap"},
                assertions=["tile_area_monotonic_with_size_metric"],
            ),
            SemanticTest(
                name="map_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="map_provider_unavailable_returns_warning_not_synthetic_zeros",
                description="When yfinance is down, rows that fail are surfaced as warnings rather than painted with color_value=0.",
                inputs={},
                assertions=[
                    "missing_row_color_value_is_null_not_zero",
                    "warning_emitted_for_failed_rows",
                ],
            ),
        ],
    )


__all__ = ["market_map"]
