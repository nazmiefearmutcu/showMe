"""FSRC — Fund Screener.

Filter the fund / ETF reference universe (US equity, international, bond,
commodity, closed-end) by category and expense ratio with a server-side
predicate query. Backend handler is ``FSRCFunction`` in
``engine/functions/screen/_funcs.py``: it serves the curated fund reference
universe and, when live is requested, overlays keyless yfinance last-price
quotes per row. Expense ratio and dividend yield are curated reference values;
AUM and YTD are not served (no provider), so predicates on them are refused.
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
            "Filter the fund and ETF universe by category and expense ratio with a predicate "
            "query, returning matching funds with curated reference expense ratio and dividend "
            "yield, and a live last-price overlay when the quote provider answers. AUM and YTD "
            "are not served."
        ),
        asset_classes=[AssetClass.FUND, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="query",
                label="Filter",
                control=ControlKind.TEXT,
                required=False,
                description=(
                    "Predicate over fund columns, e.g. expenseRatio < 0.01 AND dividend_yield > 0.03 "
                    "or category = \"Long Government\". Predicates on aum_usd or ytd_return_pct are "
                    "refused (not served)."
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
            "query": "expenseRatio < 0.01",
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
                ColumnSpec(key="expenseRatio", label="Exp%", kind="percent", format="%.3f"),
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
            "Expense ratio and dividend yield are curated reference values with no provider as-of "
            "date. AUM and YTD are not served: no keyless provider supplies them, the earlier curated "
            "figures were stale, so aum_usd and ytd_return_pct are null with aum_state / ytd_state "
            "unavailable, and a predicate on either returns status provider_unavailable with no rows. "
            "When live is requested, each row gets a yfinance last price and change percent "
            "(quote_state live) where the provider answers; rows without a quote keep quote_state "
            "reference and no price. Predicates are applied after the overlay. A query that matches "
            "no row returns status empty with next_actions, never filler rows."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Fund or ETF ticker.", source="curated"),
            "rows[].name": FieldDef(description="Fund display name.", source="curated"),
            "rows[].issuer": FieldDef(description="Fund sponsor.", source="curated"),
            "rows[].category": FieldDef(description="Fund exposure bucket.", source="curated"),
            "rows[].aum_usd": FieldDef(unit="USD", description="Not served: always null (no provider supplies fund AUM).", source="derived"),
            "rows[].aum_state": FieldDef(description="\"unavailable\" — aum_usd is not served.", source="derived"),
            "rows[].expenseRatio": FieldDef(unit="fraction", description="Curated reference annual expense ratio as a decimal (0.0009 = 0.09%); no as-of date.", source="curated_reference"),
            "rows[].ytd_return_pct": FieldDef(unit="%", description="Not served: always null (no provider supplies fund YTD returns).", source="derived"),
            "rows[].ytd_state": FieldDef(description="\"unavailable\" — ytd_return_pct is not served.", source="derived"),
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
                name="fsrc_aum_and_ytd_not_served",
                description="Every returned row has aum_usd and ytd_return_pct null with aum_state and ytd_state unavailable, and the payload warns AUM and YTD are not served.",
                inputs={"query": "expenseRatio < 0.01"},
                assertions=[
                    "rows_aum_usd_null",
                    "rows_ytd_return_pct_null",
                    "rows_aum_state_unavailable",
                    "rows_ytd_state_unavailable",
                    "warnings_mention_not_served",
                ],
            ),
            SemanticTest(
                name="fsrc_aum_predicate_refused",
                description="A predicate on aum_usd returns status provider_unavailable with rows=[] instead of matching against nothing.",
                inputs={"query": "aum_usd > 10000000000"},
                assertions=["status_equals_provider_unavailable", "rows_is_empty_array", "next_actions_present"],
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
