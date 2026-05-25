"""GLCO — Global Commodities mini-board.

Snapshot table over energy / metals / agriculture / softs futures.
Same shape as Bloomberg ``GLCO<GO>``: rows are individual contracts
with last/Δ%/sector/contract-month/OI. Renders as a bar_ladder chart
(top-mover diverging bars) so users can size the move at a glance.
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
def glco() -> FunctionManifest:
    return FunctionManifest(
        code="GLCO",
        name="Global Commodities Board",
        category=Category.COMMODITIES,
        intent=(
            "Snapshot board of the global commodity universe (energy, "
            "metals, agriculture, softs) with sector filter, last/Δ%/OI, "
            "and a top-mover bar ladder for quick visual ranking."
        ),
        asset_classes=[AssetClass.COMMODITY, AssetClass.FUTURE],
        inputs=[
            InputSpec(
                name="sector",
                label="Sector",
                control=ControlKind.SELECT,
                required=False,
                description="Restrict the board to a sub-sector.",
                options=["all", "energy", "metals", "ags", "softs"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; chain may downgrade.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "sector": "all",
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "source_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="%", label="Δ %"),
            y_axis=AxisSpec(type="category", unit="contract", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="sector", label="Sector", kind="tag"),
                ColumnSpec(key="last", label="Last", kind="number", format="%.4f"),
                ColumnSpec(key="change_pct", label="Δ %", kind="percent", format="%.2f"),
                ColumnSpec(key="contract_month", label="Contract", kind="text"),
                ColumnSpec(key="open_interest", label="OI", kind="number", format="%.0f"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="universe_size", label="Contracts", kind="kpi"),
                CardSlot(key="advancers", label="Adv", kind="kpi"),
                CardSlot(key="decliners", label="Dec", kind="kpi"),
                CardSlot(key="leader", label="Leader", kind="big_number"),
                CardSlot(key="laggard", label="Laggard", kind="big_number"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "GLCO is a curated snapshot of the global commodity board. The "
            "handler maintains a per-sector ticker list (energy: CL/BZ/NG/RB/HO; "
            "metals: GC/SI/HG/PL/PA; ags: ZC/ZS/ZW; softs: CT/KC/SB/CC) and "
            "fans out to yfinance for each row, then ranks by absolute Δ % for "
            "the bar-ladder visualization. Sector filter trims the universe "
            "before ranking. Each row carries the contract month and OI so an "
            "operator can spot a rolled contract before treating a snap-back "
            "as a real move."
        ),
        formula_dict={
            "change_pct": Formula(
                expression=r"chg\_pct = \frac{last - prev\_close}{prev\_close} \times 100",
                variables={"last": "Latest close", "prev_close": "Prior session close"},
            ),
        },
        field_dict={
            "rows[].symbol": FieldDef(description="Futures ticker (e.g. CL=F).", source="curated"),
            "rows[].sector": FieldDef(description="energy | metals | ags | softs.", source="curated"),
            "rows[].last": FieldDef(unit="USD/unit", description="Last trade price in contract unit.", source="provider"),
            "rows[].change_pct": FieldDef(unit="%", description="Session change percent.", source="computed"),
            "rows[].contract_month": FieldDef(description="Active delivery month.", source="provider"),
            "rows[].open_interest": FieldDef(unit="contracts", description="Listed open interest.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="glco_chart_is_bar_ladder",
                description="GLCO renders a bar ladder, not a row-index line.",
                inputs={},
                assertions=["chart_grammar_kind_is_bar_ladder"],
            ),
            SemanticTest(
                name="glco_all_sector_returns_rows",
                description="Default sector=all returns at least one row across sectors.",
                inputs={"sector": "all"},
                assertions=[
                    "rows_non_empty",
                    "every_row_has_symbol_and_sector",
                ],
            ),
            SemanticTest(
                name="glco_filter_energy_returns_energy_only",
                description="sector=energy filters to energy-only rows.",
                inputs={"sector": "energy"},
                assertions=["every_row_sector_is_energy"],
            ),
        ],
    )


__all__ = ["glco"]
