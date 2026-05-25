"""MOSS — Sectoral movers (gainers / losers by sector).

Sister to MOST but partitioned by GICS sector. Returns the top-N
gainers and top-N losers within each sector so an operator can spot
intra-sector dispersion (the "what's leading and lagging within
Tech" view). Rendered as side-by-side ranked bar ladders.
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
def moss() -> FunctionManifest:
    return FunctionManifest(
        code="MOSS",
        name="Sectoral Movers",
        category=Category.SCREENING,
        intent=(
            "Return top-N gainers and top-N losers within each GICS sector so an operator can spot "
            "intra-sector dispersion, with a side-by-side ranked bar ladder per sector and one-click "
            "drill into EQS for the full sector screen."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.SELECT,
                required=True,
                description="Reference universe.",
                options=["SP500", "NDX", "RUSSELL2000", "STOXX600"],
            ),
            InputSpec(
                name="sector_filter",
                label="Sectors",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to selected GICS sectors (empty = all sectors).",
                options=[
                    "Information Technology",
                    "Health Care",
                    "Financials",
                    "Consumer Discretionary",
                    "Communication Services",
                    "Industrials",
                    "Consumer Staples",
                    "Energy",
                    "Utilities",
                    "Real Estate",
                    "Materials",
                ],
            ),
            InputSpec(
                name="per_sector_n",
                label="Per sector N",
                control=ControlKind.NUMBER,
                required=True,
                description="Top-N gainers AND top-N losers returned per sector.",
                min=3,
                max=25,
                step=1,
            ),
            InputSpec(
                name="period",
                label="Period",
                control=ControlKind.SELECT,
                required=True,
                description="Performance horizon.",
                options=["1D", "5D", "MTD", "QTD", "YTD"],
            ),
            InputSpec(
                name="show_losers",
                label="Show losers",
                control=ControlKind.BOOLEAN,
                required=True,
                description="When false, only the gainers ladder is returned.",
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
            "sector_filter": [],
            "per_sector_n": 5,
            "period": "1D",
            "show_losers": True,
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
            must_have=["as_of", "rows", "period", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="%", label="Δ"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="sector", label="Sector", kind="tag"),
                ColumnSpec(key="bucket", label="Bucket", kind="tag"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.2f"),
                ColumnSpec(key="change_pct", label="Δ %", kind="percent", format="%.2f"),
                ColumnSpec(key="volume", label="Vol", kind="number", format="si"),
                ColumnSpec(key="market_cap", label="Mkt Cap", kind="currency", format="si"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="sectors_count", label="Sectors", kind="kpi"),
                CardSlot(key="rows_count", label="Rows", kind="kpi"),
                CardSlot(key="best_sector", label="Best Sector", kind="badge"),
                CardSlot(key="worst_sector", label="Worst Sector", kind="badge"),
                CardSlot(key="dispersion", label="Dispersion", kind="kpi", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "MOSS partitions the universe constituents by GICS sector (from the bundled "
            "classification map; falls back to yfinance industry call when missing). For each "
            "sector it pulls the per-period return (1D last vs prev_close; multi-day from yfinance "
            "history) for every constituent, then sorts asc/desc to slice top-N gainers (bucket="
            "gainer) and bottom-N losers (bucket=loser). When show_losers=False only the gainers "
            "ladder is returned. dispersion = stdev(returns) across all returned rows. "
            "best_sector / worst_sector are the sectors with the highest / lowest median return. "
            "Rendered as side-by-side BAR_LADDER strips, one per sector. Next actions: "
            "open_sector_in_eqs, open_in_gp, save_screen, export_csv."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Constituent ticker.", source="universe"),
            "rows[].name": FieldDef(description="Issuer name.", source="yfinance"),
            "rows[].sector": FieldDef(description="GICS sector tag.", source="classification"),
            "rows[].bucket": FieldDef(description="gainer | loser.", source="derived"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Last trade price.", source="yfinance"),
            "rows[].change_pct": FieldDef(unit="%", description="Period return in percent.", source="computed"),
            "rows[].volume": FieldDef(unit="shares", description="Session volume.", source="yfinance"),
            "rows[].market_cap": FieldDef(unit="USD", description="Market capitalization.", source="yfinance"),
            "dispersion": FieldDef(unit="%", description="Stdev of returns across returned rows.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="moss_chart_grammar_is_bar_ladder",
                description="MOSS manifest pins chart_grammar.kind to bar_ladder (per-sector gainer/loser ladders).",
                inputs={},
                assertions=["manifest.chart_grammar.kind == 'bar_ladder'"],
            ),
            SemanticTest(
                name="moss_per_sector_n_respected_both_buckets",
                description="For each sector the rows include at most per_sector_n with bucket=gainer and per_sector_n with bucket=loser.",
                inputs={"per_sector_n": 5},
                assertions=[
                    "per_sector_gainers_at_most_5",
                    "per_sector_losers_at_most_5",
                ],
            ),
            SemanticTest(
                name="moss_show_losers_false_omits_loser_bucket",
                description="With show_losers=False the rows contain no bucket=loser entries.",
                inputs={"show_losers": False},
                assertions=["no_rows_with_bucket_loser"],
            ),
            SemanticTest(
                name="moss_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="moss_sector_filter_restricts_rows",
                description="With sector_filter=['Information Technology'] every row's sector equals that value.",
                inputs={"sector_filter": ["Information Technology"]},
                assertions=["all_rows_sector_equals_information_technology"],
            ),
        ],
    )


__all__ = ["moss"]
