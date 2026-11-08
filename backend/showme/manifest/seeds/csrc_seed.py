"""CSRC — Commodity Screener.

Filter the curated liquid futures complex (energy, metals, grains, softs,
livestock) by sector and a query predicate, returning each contract with its
unit and the latest Yahoo front-month quote. Backend handler is
``engine/functions/screen/_funcs.py`` (``CSRCFunction``): contracts come from
the bundled commodity reference universe and quotes from yfinance ``=F``
tickers. Contracts the quote provider does not answer stay in the payload
labelled ``quote_state="reference"``.
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
def csrc() -> FunctionManifest:
    return FunctionManifest(
        code="CSRC",
        name="Commodity Screener",
        category=Category.SCREENING,
        intent=(
            "Filter the liquid commodity futures complex (energy, metals, grains, softs, livestock) "
            "by sector and query predicate, with each contract's unit and latest front-month quote. "
            "Quotes come from Yahoo futures (=F tickers); contracts the provider does not answer "
            "stay visible and labelled as reference rows."
        ),
        asset_classes=[AssetClass.COMMODITY],
        inputs=[
            InputSpec(
                name="sector",
                label="Sector",
                control=ControlKind.SELECT,
                required=False,
                description="Commodity sector to scan; 'all' keeps every contract in the complex.",
                options=["all", "Energy", "Metals", "Grains", "Softs", "Livestock"],
            ),
            InputSpec(
                name="query",
                label="Filter",
                control=ControlKind.TEXT,
                required=False,
                description='Predicate over the result fields, e.g. sector = "Energy" AND change_pct > 0.',
            ),
            InputSpec(
                name="limit",
                label="Row limit",
                control=ControlKind.SELECT,
                required=True,
                description="Cap on matched-row results.",
                options=[25, 50, 100],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred mode; chain may downgrade and report it.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "sector": "all",
            "limit": 50,
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
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "rows", "matched", "scanned"],
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
                ColumnSpec(key="contract_unit", label="Unit", kind="text"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.4f"),
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
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "CSRC filters the bundled commodity reference universe (one front-month contract per "
            "market, grouped into Energy, Metals, Grains, Softs and Livestock) with the sector and "
            "query predicates. With live quotes enabled each contract is requested from yfinance "
            "using its =F ticker, under a bounded per-symbol timeout. Contracts without a usable "
            "quote keep their reference fields and carry quote_state=reference. volume is the quote "
            "provider's session volume and is null when no quote carries one. open_interest is a "
            "curated reference value for the legacy contracts only; the quote provider does not "
            "publish open interest, and contracts without a curated value carry null rather than "
            "zero. Matches are sorted by volume by default."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Yahoo front-month futures ticker (e.g. CL=F).", source="universe"),
            "rows[].name": FieldDef(description="Contract name (WTI Crude Oil, Corn, Live Cattle, …).", source="curated"),
            "rows[].sector": FieldDef(description="Commodity sector: Energy, Metals, Grains, Softs or Livestock.", source="curated"),
            "rows[].contract_unit": FieldDef(description="Contract size and unit.", source="curated"),
            "rows[].last": FieldDef(unit="quote_ccy", description="Latest futures price from the quote provider.", source="yfinance"),
            "rows[].change_pct": FieldDef(unit="%", description="Percent move versus the previous close when a live quote exists.", source="yfinance"),
            "rows[].volume": FieldDef(unit="contracts", description="Session volume from the quote provider; null when the provider did not return one.", source="yfinance"),
            "rows[].open_interest": FieldDef(unit="contracts", description="Curated reference open interest; null when not curated.", source="curated"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="csrc_sector_filter_restricts_rows",
                description="With sector=Energy every row's sector field equals 'Energy'.",
                inputs={"sector": "Energy"},
                assertions=["all_rows_sector_equals_energy"],
            ),
            SemanticTest(
                name="csrc_missing_oi_is_null_not_zero",
                description="A contract without a curated open interest carries open_interest=null, never 0.",
                inputs={},
                assertions=["missing_oi_row_open_interest_is_null_not_zero"],
            ),
            SemanticTest(
                name="csrc_provider_unavailable_keeps_reference_rows_labelled",
                description="When yfinance returns nothing, rows keep reference fields and quote_state=reference with no synthetic prices.",
                inputs={},
                assertions=[
                    "rows_quote_state_reference_when_unquoted",
                    "no_synthetic_fields",
                ],
            ),
        ],
    )


__all__ = ["csrc"]
