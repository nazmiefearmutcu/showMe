"""SECT — Sector rotation view.

Bloomberg ``SECT<GO>`` analogue. Aggregates equity sector performance
(by SPDR sector ETFs and constituent breadth) and ranks them across
multiple horizons (1D/5D/MTD/QTD/YTD) so an operator can read
rotation signals. UI hangs off the same MarketHeatmapPane as MAP but
the manifest grammar is BAR_LADDER (ranked horizontal bars) to make
the rotation explicit.
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
        name="Sector Rotation",
        category=Category.SCREENING,
        intent=(
            "Rank equity sectors by performance across multiple horizons (1D/5D/MTD/QTD/YTD) and "
            "breadth metrics so an operator can read rotation signals, with one-click drill-down to "
            "constituent screens per sector."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.SELECT,
                required=True,
                description="Reference universe whose constituent breadth feeds the rank.",
                options=["SP500", "NDX", "STOXX600"],
            ),
            InputSpec(
                name="period",
                label="Period",
                control=ControlKind.SELECT,
                required=True,
                description="Performance horizon driving the rank.",
                options=["1D", "5D", "MTD", "QTD", "YTD", "1Y"],
            ),
            InputSpec(
                name="metric",
                label="Metric",
                control=ControlKind.SELECT,
                required=True,
                description="What to rank by.",
                options=["return_pct", "weighted_return_pct", "advancers_ratio", "median_return_pct"],
            ),
            InputSpec(
                name="show_breadth",
                label="Breadth chips",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Show advancers/decliners breadth chip per sector.",
            ),
            InputSpec(
                name="saved_screen",
                label="Saved screen",
                control=ControlKind.SELECT,
                required=False,
                description="Load a previously saved sector view.",
                options=["SPDR-1D", "SPDR-YTD", "STOXX-MTD"],
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
            "period": "1D",
            "metric": "return_pct",
            "show_breadth": True,
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
            must_have=["as_of", "rows", "period", "metric", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="%", label="Return"),
            y_axis=AxisSpec(type="category", unit="", label="Sector"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="sector", label="Sector", kind="text"),
                ColumnSpec(key="etf_symbol", label="ETF", kind="tag"),
                ColumnSpec(key="weight", label="Weight", kind="percent", format="%.2f"),
                ColumnSpec(key="return_pct", label="Return", kind="percent", format="%.2f"),
                ColumnSpec(key="advancers", label="Up", kind="number", format="%d"),
                ColumnSpec(key="decliners", label="Down", kind="number", format="%d"),
                ColumnSpec(key="advancers_ratio", label="A/D", kind="percent", format="%.1f"),
                ColumnSpec(key="median_return_pct", label="Median Δ", kind="percent", format="%.2f"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="leader", label="Leader", kind="badge"),
                CardSlot(key="laggard", label="Laggard", kind="badge"),
                CardSlot(key="dispersion", label="Dispersion", kind="kpi", unit="%"),
                CardSlot(key="rotation_score", label="Rotation", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "SECT joins two data feeds. (1) SPDR sector ETF tape — XLF, XLK, XLE, XLV, XLI, XLP, "
            "XLY, XLU, XLB, XLRE, XLC — gives the canonical per-sector return at each period via "
            "yfinance history. (2) Constituent breadth — for the chosen universe SECT classifies "
            "each ticker by its GICS sector and aggregates advancers/decliners + median_return_pct "
            "for that period. The two views are joined on sector key and ranked by `metric`. "
            "rotation_score = dispersion-normalized z-score of returns across sectors (higher → "
            "more rotation). Cap-weighted return uses constituent market_cap from yfinance. Visual "
            "is a horizontal BAR_LADDER ranked by `metric`. Next actions: open_sector_constituents "
            "(launches EQS with sector predicate), open_in_gp on ETF, save_screen, export_csv."
        ),
        field_dict={
            "rows[].sector": FieldDef(description="GICS sector name.", source="curated"),
            "rows[].etf_symbol": FieldDef(description="SPDR sector ETF ticker (XLF, XLK, …).", source="curated"),
            "rows[].weight": FieldDef(unit="%", description="Sector cap weight within the universe.", source="computed"),
            "rows[].return_pct": FieldDef(unit="%", description="Sector ETF return over period.", source="yfinance"),
            "rows[].advancers": FieldDef(unit="count", description="Constituents with positive return over period.", source="computed"),
            "rows[].decliners": FieldDef(unit="count", description="Constituents with negative return over period.", source="computed"),
            "rows[].advancers_ratio": FieldDef(unit="%", description="advancers / (advancers + decliners) * 100.", source="computed"),
            "rows[].median_return_pct": FieldDef(unit="%", description="Median constituent return over period.", source="computed"),
            "rotation_score": FieldDef(description="Cross-sector dispersion z-score.", source="computed"),
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
                description="SECT manifest pins chart_grammar.kind to bar_ladder (ranked sector return ladder).",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'bar_ladder'"],
            ),
            SemanticTest(
                name="sect_metric_return_pct_sort_is_monotonic",
                description="With metric=return_pct the rows are monotonically non-increasing in return_pct.",
                inputs={"metric": "return_pct"},
                assertions=["rows_monotonically_non_increasing_in_return_pct"],
            ),
            SemanticTest(
                name="sect_breadth_advancers_plus_decliners_le_universe_size",
                description="advancers + decliners per row is <= the universe constituent count classified into that sector.",
                inputs={},
                assertions=["per_row_advancers_plus_decliners_le_sector_size"],
            ),
            SemanticTest(
                name="sect_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="sect_provider_unavailable_returns_warning_not_synthetic_zeros",
                description="When yfinance is down, missing-return rows surface as warnings rather than return_pct=0.",
                inputs={},
                assertions=[
                    "missing_row_return_pct_is_null_not_zero",
                    "warning_emitted_for_failed_rows",
                ],
            ),
        ],
    )


__all__ = ["sect"]
