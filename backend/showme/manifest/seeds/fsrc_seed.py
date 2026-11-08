"""FSRC — Fund Screener.

Filter the fund / ETF reference universe (US equity, international, bond,
commodity, closed-end) by category, expense ratio and AUM with a server-side
predicate query. Backend handler is ``FSRCFunction`` in
``engine/functions/screen/_funcs.py``: it serves the curated fund reference
universe and, when live is requested, overlays keyless yfinance last-price
quotes per row. AUM, expense ratio and YTD are curated reference values.
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
        name="Fund Screener",
        category=Category.SCREENING,
        intent=(
            "Filter the fund and ETF universe by category, expense ratio and AUM with a predicate "
            "query, returning matching funds with curated reference AUM, expense ratio and YTD, "
            "and a live last-price overlay when the quote provider answers."
        ),
        asset_classes=[AssetClass.ETF],
        inputs=[
            InputSpec(
                name="query",
                label="Filter",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Predicate over fund columns, e.g. expenseRatio < 0.01 AND aum_usd > 10000000000 "
                    "or category = \"Long Government\"."
                ),
            ),
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.TEXT,
                required=False,
                description="Optional comma-separated fund tickers to restrict the screen to.",
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
                name="live",
                label="Live quotes",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "Overlay keyless yfinance last-price quotes per row. Setting live false or "
                    "reference true serves the curated reference universe only."
                ),
            ),
            InputSpec(
                name="reference",
                label="Reference only",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Serve the curated reference universe only; no quote provider call.",
            ),
        ],
        defaults={
            "query": "expenseRatio < 0.01 AND aum_usd > 10000000000",
            "limit": 50,
            "live": True,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["status", "rows", "matched", "scanned", "sources"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="name", label="Fund", kind="text"),
                ColumnSpec(key="issuer", label="Issuer", kind="text"),
                ColumnSpec(key="category", label="Category", kind="tag"),
                ColumnSpec(key="aum_usd", label="AUM (ref)", kind="currency", format="si"),
                ColumnSpec(key="expenseRatio", label="Exp%", kind="percent", format="%.3f"),
                ColumnSpec(key="ytd_return_pct", label="YTD% (ref)", kind="percent", format="%.2f"),
                ColumnSpec(key="last", label="Last", kind="currency", format="%.2f"),
                ColumnSpec(key="change_pct", label="Change %", kind="percent", format="%.2f"),
                ColumnSpec(key="dividend_yield", label="Div%", kind="percent", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="matched", label="Matched", kind="kpi"),
                CardSlot(key="scanned", label="Scanned", kind="kpi"),
                CardSlot(key="status", label="Status", kind="badge"),
            ],
        ),
        methodology=(
            "FSRC filters a curated fund and ETF reference universe with the predicate query. "
            "AUM, expense ratio, YTD and dividend yield are curated reference values with no as-of "
            "date; they are labelled aum_state / ytd_state reference on every row and are not "
            "refreshed from a provider. When live is requested, each row gets a yfinance last price "
            "and change percent (quote_state live) where the provider answers; rows without a quote "
            "keep quote_state reference and no price. Predicates are applied after the overlay. "
            "A query that matches no row returns status empty with next_actions, never filler rows."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Fund or ETF ticker.", source="curated"),
            "rows[].name": FieldDef(description="Fund display name.", source="curated"),
            "rows[].issuer": FieldDef(description="Fund sponsor.", source="curated"),
            "rows[].category": FieldDef(description="Fund exposure bucket.", source="curated"),
            "rows[].aum_usd": FieldDef(unit="USD", description="Curated reference AUM; no as-of date.", source="curated_reference"),
            "rows[].aum_state": FieldDef(description="\"reference\" for curated AUM.", source="derived"),
            "rows[].expenseRatio": FieldDef(unit="fraction", description="Annual expense ratio as a decimal (0.0009 = 0.09%).", source="curated_reference"),
            "rows[].ytd_return_pct": FieldDef(unit="%", description="Curated reference year-to-date return; no as-of date.", source="curated_reference"),
            "rows[].ytd_state": FieldDef(description="\"reference\" for curated YTD.", source="derived"),
            "rows[].dividend_yield": FieldDef(unit="fraction", description="Curated reference dividend yield as a decimal.", source="curated_reference"),
            "rows[].last": FieldDef(unit="USD", description="Latest traded price when the live overlay answers.", source="yfinance"),
            "rows[].change_pct": FieldDef(unit="%", description="Percent move versus previous close when the live overlay answers.", source="yfinance"),
            "rows[].quote_state": FieldDef(description="\"live\" when a quote was overlaid, else \"reference\".", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=False,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fsrc_category_predicate_restricts_rows",
                description="With category = \"Long Government\" every row's category equals 'Long Government'.",
                inputs={"query": "category = \"Long Government\""},
                assertions=["all_rows_category_equals_long_government"],
            ),
            SemanticTest(
                name="fsrc_expense_predicate_respected",
                description="With expenseRatio <= 0.001 every returned row has expenseRatio <= 0.001.",
                inputs={"query": "expenseRatio <= 0.001"},
                assertions=["all_rows_expense_ratio_at_most_0_001"],
            ),
            SemanticTest(
                name="fsrc_curated_aum_and_ytd_labelled_reference",
                description="Every returned row carries aum_state and ytd_state reference, and the payload warns they are curated.",
                inputs={},
                assertions=[
                    "rows_aum_state_reference",
                    "rows_ytd_state_reference",
                    "warnings_mention_curated_reference",
                ],
            ),
            SemanticTest(
                name="fsrc_no_match_returns_empty_not_filler",
                description="A query that matches no fund returns status empty with rows=[] and next_actions.",
                inputs={"query": "expenseRatio < 0"},
                assertions=["status_equals_empty", "rows_is_empty_array", "next_actions_present"],
            ),
        ],
    )


__all__ = ["fsrc"]
