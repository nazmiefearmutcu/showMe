"""FA — Financial Analysis (income / balance / cash flow / ratios).

SEC EDGAR XBRL is the canonical source for US equities; yfinance is the
global fallback. Both are normalized through ``_normalise_fa_payload``
into the same canonical wire shape with income_statement, balance_sheet,
cash_flow, and ratios.
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
def fa() -> FunctionManifest:
    return FunctionManifest(
        code="FA",
        name="Financial Analysis",
        category=Category.EQUITIES,
        intent=(
            "Inspect a company's income statement, balance sheet, cash flow, and computed ratios "
            "with a 5-year trend per line item."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity or ETF ticker.",
            ),
            InputSpec(
                name="period",
                label="Period",
                control=ControlKind.SELECT,
                required=True,
                description="Reporting period for statement rows.",
                options=["annual", "quarterly"],
            ),
            InputSpec(
                name="tab",
                label="Statement",
                control=ControlKind.SELECT,
                required=False,
                description="Visible statement tab in the UI; backend always returns all four.",
                options=["income", "balance", "cash", "ratios"],
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "period": "annual",
            "tab": "income",
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="sec_edgar",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=21600, scope="per_input", persist=True),
        # Matches _normalise_fa_payload return shape. The three statement
        # arrays are required even if a section is empty so the UI can show
        # an "empty" state without guessing the field name.
        output_contract=OutputContract(
            must_have=[
                "symbol",
                "status",
                "period",
                "income_statement",
                "balance_sheet",
                "cash_flow",
                "ratios",
            ],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="line_item", label="Line item", kind="text"),
                ColumnSpec(key="latest", label="Latest", kind="number", format="%.0f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="revenue", label="Revenue", kind="big_number", unit="quote_ccy"),
                CardSlot(key="gross_margin", label="Gross margin", kind="kpi", unit="%"),
                CardSlot(key="operating_margin", label="Op. margin", kind="kpi", unit="%"),
                CardSlot(key="net_margin", label="Net margin", kind="kpi", unit="%"),
                CardSlot(key="return_on_equity", label="ROE", kind="kpi", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FA prefers SEC EDGAR XBRL (canonical, US-only) and falls back to yfinance for global "
            "coverage. _normalise_fa_payload maps each provider's native labels to the shared canonical "
            "set (SEC_CANONICAL_ALIASES, YF_CANONICAL_ALIASES), extracts the most recent 5 periods per "
            "line item, and computes ratios (gross/op/net margin, ROA, ROE, debt/equity, current ratio, "
            "FCF margin) from the latest values. When both providers fail status is set to "
            "provider_unavailable and next_actions point operators at the missing feed."
        ),
        formula_dict={
            "gross_margin": Formula(
                expression=r"gross\_margin = \frac{gross\_profit}{revenue}",
                variables={"gross_profit": "Gross profit", "revenue": "Total revenue"},
            ),
            "operating_margin": Formula(
                expression=r"op\_margin = \frac{operating\_income}{revenue}",
                variables={"operating_income": "Operating income", "revenue": "Total revenue"},
            ),
            "net_margin": Formula(
                expression=r"net\_margin = \frac{net\_income}{revenue}",
                variables={"net_income": "Net income", "revenue": "Total revenue"},
            ),
            "return_on_equity": Formula(
                expression=r"ROE = \frac{net\_income}{total\_equity}",
                variables={"net_income": "Net income", "total_equity": "Stockholders' equity"},
            ),
            "free_cash_flow": Formula(
                expression=r"FCF = CFO - |capex|",
                variables={"CFO": "Cash from operations", "capex": "Capital expenditure"},
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "period": FieldDef(description="annual | quarterly.", source="input"),
            "source": FieldDef(description="sec_edgar | yfinance.", source="alias"),
            "income_statement": FieldDef(description="Canonical income-statement rows.", source="provider"),
            "balance_sheet": FieldDef(description="Canonical balance-sheet rows.", source="provider"),
            "cash_flow": FieldDef(description="Canonical cash-flow rows.", source="provider"),
            "ratios": FieldDef(description="Computed margin/return/leverage ratios.", source="computed"),
            "statement_counts": FieldDef(description="Row counts per statement section.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="fa_aapl_annual_returns_canonical_statements",
                description="FA for AAPL annual returns non-empty income/balance/cash arrays with canonical line_items.",
                inputs={"symbol": "AAPL", "period": "annual"},
                assertions=[
                    "status_in_ok_set",
                    "income_statement_non_empty",
                    "balance_sheet_non_empty",
                    "cash_flow_non_empty",
                    "ratios_non_empty",
                    "source_in_known_set",
                ],
            ),
            SemanticTest(
                name="fa_ratios_match_formula",
                description="Computed gross_margin equals gross_profit / revenue from the same latest values.",
                inputs={"symbol": "MSFT", "period": "annual"},
                assertions=[
                    "gross_margin_equals_gross_profit_over_revenue",
                ],
            ),
            SemanticTest(
                name="fa_provider_outage_returns_unavailable_not_fake_statements",
                description="When both SEC and yfinance fail, status is provider_unavailable and statement arrays are empty (not fabricated).",
                inputs={"symbol": "ZZZZZZ", "period": "annual"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "income_statement_is_empty_array",
                    "balance_sheet_is_empty_array",
                    "cash_flow_is_empty_array",
                    "next_actions_non_empty",
                ],
            ),
        ],
    )


__all__ = ["fa"]
