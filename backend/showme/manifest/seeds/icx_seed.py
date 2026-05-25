"""ICX — Industry classification explorer.

Bloomberg ``ICX<GO>`` analogue. Navigate the GICS / BICS / ICB
hierarchy with constituent counts, aggregate cap weights, and breadth
metrics per node so an operator can drill from Sector → Industry
Group → Industry → Sub-Industry and surface the canonical
classification for any ticker.
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
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def icx() -> FunctionManifest:
    return FunctionManifest(
        code="ICX",
        name="Industry Classification Explorer",
        category=Category.SCREENING,
        intent=(
            "Navigate the GICS hierarchy (Sector → Industry Group → Industry → Sub-Industry) with "
            "constituent counts, weight, and breadth per node so an operator can drill into any "
            "classification level and surface the canonical industry for any ticker."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="taxonomy",
                label="Taxonomy",
                control=ControlKind.SELECT,
                required=True,
                description="Classification standard to navigate.",
                options=["GICS", "BICS", "ICB"],
            ),
            InputSpec(
                name="level",
                label="Level",
                control=ControlKind.SELECT,
                required=True,
                description="Hierarchy level to surface.",
                options=["sector", "industry_group", "industry", "sub_industry"],
            ),
            InputSpec(
                name="parent",
                label="Parent",
                control=ControlKind.TEXT,
                required=False,
                description="Restrict to children of this parent (e.g. sector name when level=industry_group).",
                depends_on=["level"],
            ),
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.SELECT,
                required=True,
                description="Reference universe for constituent counts and weight.",
                options=["SP500", "NDX", "DJIA", "RUSSELL2000", "STOXX600"],
            ),
            InputSpec(
                name="query_symbol",
                label="Symbol lookup",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Show the canonical classification path for a single symbol.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "taxonomy": "GICS",
            "level": "sector",
            "universe": "SP500",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["openfigi", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "taxonomy", "level", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="code", label="Code", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="parent", label="Parent", kind="tag"),
                ColumnSpec(key="constituent_count", label="N", kind="number", format="%d"),
                ColumnSpec(key="weight_pct", label="Weight", kind="percent", format="%.2f"),
                ColumnSpec(key="advancers_ratio", label="A/D", kind="percent", format="%.1f"),
                ColumnSpec(key="median_return_pct", label="Median Δ", kind="percent", format="%.2f"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_nodes", label="Nodes", kind="kpi"),
                CardSlot(key="total_constituents", label="Constituents", kind="kpi"),
                CardSlot(key="taxonomy", label="Taxonomy", kind="badge"),
                CardSlot(key="level", label="Level", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ICX walks the GICS tree (or BICS / ICB when configured). The classification map ships in "
            "a bundled JSON of (sector_code, sector_name, industry_group_code, industry_group_name, "
            "industry_code, industry_name, sub_industry_code, sub_industry_name) — 11 / 25 / 74 / 163 "
            "nodes for GICS. For each node at the requested level ICX joins the universe's "
            "constituent ticker list with yfinance industry classification calls (cached 1h in "
            "DuckDB) to count constituents and aggregate cap weight + breadth. When query_symbol is "
            "set, ICX returns the single-row canonical path for that ticker rather than the level "
            "listing. parent filters the listing to children of the named parent. Next actions: "
            "drill_into_node, list_constituents (opens EQS with industry predicate), open_in_gp, "
            "save_screen."
        ),
        field_dict={
            "rows[].code": FieldDef(description="Numeric classification code (e.g. GICS sector code 45).", source="taxonomy"),
            "rows[].name": FieldDef(description="Classification node name.", source="taxonomy"),
            "rows[].parent": FieldDef(description="Parent node name in the hierarchy.", source="taxonomy"),
            "rows[].constituent_count": FieldDef(unit="count", description="Tickers from `universe` classified into this node.", source="computed"),
            "rows[].weight_pct": FieldDef(unit="%", description="Aggregate cap weight of constituents within `universe`.", source="computed"),
            "rows[].advancers_ratio": FieldDef(unit="%", description="advancers / (advancers + decliners) * 100 for constituents.", source="computed"),
            "rows[].median_return_pct": FieldDef(unit="%", description="Median 1-day return across constituents.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="icx_gics_sector_level_returns_eleven_rows",
                description="taxonomy=GICS + level=sector returns exactly 11 rows (the canonical GICS sectors).",
                inputs={"taxonomy": "GICS", "level": "sector"},
                assertions=["row_count_equals_11"],
            ),
            SemanticTest(
                name="icx_parent_filter_restricts_to_children",
                description="With level=industry_group + parent='Information Technology' every row's parent equals that sector.",
                inputs={"taxonomy": "GICS", "level": "industry_group", "parent": "Information Technology"},
                assertions=["all_rows_parent_equals_information_technology"],
            ),
            SemanticTest(
                name="icx_query_symbol_returns_canonical_path",
                description="query_symbol=AAPL returns a single row with the canonical GICS path (Information Technology → Technology Hardware → Technology Hardware, Storage & Peripherals).",
                inputs={"query_symbol": "AAPL"},
                assertions=[
                    "row_count_equals_one",
                    "row_canonical_path_includes_information_technology",
                ],
            ),
            SemanticTest(
                name="icx_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="icx_unknown_symbol_returns_empty_not_synthetic",
                description="query_symbol=ZZZZZZ returns rows=[] with a warning, not a synthesized 'Unknown' row.",
                inputs={"query_symbol": "ZZZZZZ"},
                assertions=[
                    "rows_is_empty_array",
                    "warning_present",
                    "no_synthetic_fields",
                ],
            ),
        ],
    )


__all__ = ["icx"]
