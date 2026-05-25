"""FSRC — Futures screener.

Filter the futures universe (energy/metals/grains/financials/softs)
by contract month, open interest, daily change, and volume. Backend
handler is ``engine/functions/screening/fsrc.py`` which pulls front-
month futures from yfinance (=F suffix) and resolves contract month
ladders for sectoral aggregates.
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
def fsrc() -> FunctionManifest:
    return FunctionManifest(
        code="FSRC",
        name="Futures Screener",
        category=Category.SCREENING,
        intent=(
            "Filter the listed futures universe by sector (energy, metals, grains, financials, softs), "
            "contract month, daily change, and open interest, returning the matching contracts with "
            "front/next-month columns and one-click GP/HP drill-downs."
        ),
        asset_classes=[AssetClass.FUTURE, AssetClass.COMMODITY],
        inputs=[
            InputSpec(
                name="sector",
                label="Sector",
                control=ControlKind.SELECT,
                required=True,
                description="Commodity sector to scan.",
                options=["all", "energy", "metals", "grains", "softs", "livestock", "financials", "currencies"],
            ),
            InputSpec(
                name="contract_month",
                label="Contract month",
                control=ControlKind.SELECT,
                required=True,
                description="Which contract month to surface (front month is default).",
                options=["front", "next", "back", "all"],
            ),
            InputSpec(
                name="min_open_interest",
                label="Min OI",
                control=ControlKind.NUMBER,
                required=False,
                description="Floor on open interest (contracts).",
                min=0,
                max=10_000_000,
                step=1000,
                unit="contracts",
            ),
            InputSpec(
                name="min_volume",
                label="Min volume",
                control=ControlKind.NUMBER,
                required=False,
                description="Floor on session volume (contracts).",
                min=0,
                max=10_000_000,
                step=1000,
                unit="contracts",
            ),
            InputSpec(
                name="saved_screen",
                label="Saved screen",
                control=ControlKind.SELECT,
                required=False,
                description="Load a previously saved futures screen.",
                options=["ENERGY-FRONT", "METALS-MOV", "GRAINS-OI", "FX-FUT"],
            ),
            InputSpec(
                name="limit",
                label="Row limit",
                control=ControlKind.SELECT,
                required=True,
                description="Cap on matched-row results.",
                options=[25, 50, 100, 250],
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
            "sector": "all",
            "contract_month": "front",
            "min_open_interest": 1000,
            "min_volume": 100,
            "limit": 50,
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
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "matched", "scanned", "sector", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Contract", kind="text"),
                ColumnSpec(key="name", label="Name", kind="text"),
                ColumnSpec(key="sector", label="Sector", kind="tag"),
                ColumnSpec(key="month", label="Month", kind="text"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.3f"),
                ColumnSpec(key="change", label="Δ", kind="currency", format="%.3f"),
                ColumnSpec(key="change_pct", label="Δ %", kind="percent", format="%.2f"),
                ColumnSpec(key="volume", label="Vol", kind="number", format="si"),
                ColumnSpec(key="open_interest", label="OI", kind="number", format="si"),
                ColumnSpec(key="actions", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matched", label="Matched", kind="kpi"),
                CardSlot(key="scanned", label="Scanned", kind="kpi"),
                CardSlot(key="median_change_pct", label="Median Δ", kind="trend_pill", unit="%"),
                CardSlot(key="top_sector", label="Top Sector", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FSRC enumerates a curated futures universe partitioned by sector (energy: CL/NG/RB/HO, "
            "metals: GC/SI/HG/PA/PL, grains: ZC/ZS/ZW/KE, softs: CT/CC/KC/SB, livestock: HE/LE, "
            "financials: ES/NQ/RTY/ZB/ZN, currencies: 6E/6J/6B/6A/6C). For contract_month=front the "
            "scanner uses yfinance =F suffix tickers; for next/back it walks the listed maturity "
            "ladder. Each row pulls last/change/volume from yfinance with a 5-min DuckDB cache. "
            "Open-interest comes from the daily settlement CSV when available; rows missing OI carry "
            "a warning rather than a synthesized 0. Predicates min_open_interest, min_volume, and "
            "sector are applied; matches are sorted by abs(change_pct) desc by default. Next actions: "
            "save_screen, export_csv, open_in_gp."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Futures root + month code (e.g. CLZ25 or =F front).", source="universe"),
            "rows[].name": FieldDef(description="Display name (Crude Oil, Gold, …).", source="curated"),
            "rows[].sector": FieldDef(description="Commodity sector tag.", source="curated"),
            "rows[].month": FieldDef(description="Contract month (FRONT/NEXT/BACK or YYYY-MM).", source="derived"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Last settlement or trade.", source="yfinance"),
            "rows[].change": FieldDef(unit="quote_ccy", description="last - prev_close.", source="computed"),
            "rows[].change_pct": FieldDef(unit="%", description="change / prev_close * 100.", source="computed"),
            "rows[].volume": FieldDef(unit="contracts", description="Session volume in contracts.", source="yfinance"),
            "rows[].open_interest": FieldDef(unit="contracts", description="Outstanding open interest.", source="cme_settlement"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fsrc_sector_filter_restricts_rows",
                description="With sector=energy every row's sector field equals 'energy'.",
                inputs={"sector": "energy"},
                assertions=["all_rows_sector_equals_energy"],
            ),
            SemanticTest(
                name="fsrc_min_oi_filter_respected",
                description="Every returned row has open_interest >= min_open_interest (when OI is available).",
                inputs={"min_open_interest": 10_000},
                assertions=["all_rows_above_oi_floor_or_carries_warning"],
            ),
            SemanticTest(
                name="fsrc_next_actions_include_save_export_and_open_gp",
                description="next_actions list always contains save_screen, export_csv, and open_in_gp entries.",
                inputs={},
                assertions=[
                    "next_actions_contains_save_screen",
                    "next_actions_contains_export_csv",
                    "next_actions_contains_open_in_gp",
                ],
            ),
            SemanticTest(
                name="fsrc_missing_oi_emits_warning_not_zero",
                description="A contract without published OI carries a warning rather than open_interest=0.",
                inputs={},
                assertions=[
                    "missing_oi_row_warning_present",
                    "missing_oi_row_open_interest_is_null_not_zero",
                ],
            ),
            SemanticTest(
                name="fsrc_provider_unavailable_returns_empty_rows_not_synthetic",
                description="When yfinance is unreachable, rows=[] and data_mode=provider_unavailable with no synthetic settles.",
                inputs={},
                assertions=[
                    "rows_is_empty_array_on_provider_failure",
                    "data_mode_equals_provider_unavailable",
                    "no_synthetic_fields",
                ],
            ),
        ],
    )


__all__ = ["fsrc"]
