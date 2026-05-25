"""FORM4 — SEC Form 4 (insider transactions) calendar.

Form 4 filings are the canonical source for officer/director transactions.
SEC EDGAR is primary; yfinance carries a derivative insider-roster view as
fallback. Renders chronologically with filer, role, transaction type, share
delta, and direct filing URL.
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
def form4() -> FunctionManifest:
    return FunctionManifest(
        code="FORM4",
        name="Insider Transactions (Form 4)",
        category=Category.EQUITIES,
        intent=(
            "List recent SEC Form 4 insider transactions (officer/director buys + sells) ranked "
            "by transaction date with filer, role, share delta, and the SEC filing URL."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker.",
            ),
            InputSpec(
                name="months",
                label="History (months)",
                control=ControlKind.NUMBER,
                required=False,
                description="Lookback for the filing list.",
                min=1,
                max=24,
                step=1,
                unit="months",
            ),
            InputSpec(
                name="transaction_types",
                label="Transaction types",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter to buy / sell / grant / option_exercise.",
                options=["buy", "sell", "grant", "option_exercise"],
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
        defaults={"months": 6, "provider_mode": DataMode.LIVE_OFFICIAL.value},
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
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="transaction_date", label="Date", kind="date"),
                ColumnSpec(key="filer", label="Filer", kind="text"),
                ColumnSpec(key="role", label="Role", kind="tag"),
                ColumnSpec(key="transaction_type", label="Type", kind="tag"),
                ColumnSpec(key="shares", label="Shares", kind="number", format="%.0f"),
                ColumnSpec(key="price", label="Price", kind="currency", format="%.2f"),
                ColumnSpec(key="value", label="Notional", kind="currency", format="%.0f"),
                ColumnSpec(key="filing_url", label="Filing", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="filing_count", label="Filings", kind="big_number"),
                CardSlot(key="net_shares", label="Net shares", kind="trend_pill"),
                CardSlot(key="net_notional", label="Net notional", kind="trend_pill", unit="quote_ccy"),
                CardSlot(key="buyer_count", label="Buyers", kind="kpi"),
                CardSlot(key="seller_count", label="Sellers", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "FORM4 queries SEC EDGAR for the issuer's recent Form 4 filings (lookback = `months`) "
            "and parses each into a typed row (transaction_date, filer name, role, transaction "
            "type — buy / sell / grant / option_exercise, share delta, price, notional, filing URL). "
            "Net shares + net notional are signed sums; buyers / sellers are distinct filer counts "
            "by direction. The transaction_types filter is applied server-side. yfinance is a "
            "best-effort fallback when EDGAR is unreachable but carries less granular data."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "rows": FieldDef(description="Per-filing Form 4 transaction rows.", source="sec_edgar"),
            "filing_count": FieldDef(description="Total filings in the lookback window.", source="computed"),
            "net_shares": FieldDef(description="Sum of signed share deltas (buys − sells).", source="computed"),
            "net_notional": FieldDef(unit="quote_ccy", description="Sum of signed notional.", source="computed"),
            "buyer_count": FieldDef(description="Distinct filers with at least one buy.", source="computed"),
            "seller_count": FieldDef(description="Distinct filers with at least one sell.", source="computed"),
            "filing_url": FieldDef(description="Direct SEC EDGAR Form 4 URL.", source="sec_edgar"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="form4_aapl_returns_recent_filings",
                description="FORM4 for AAPL returns recent insider rows with filing URLs.",
                inputs={"symbol": "AAPL", "months": 6},
                assertions=[
                    "status_in_ok_set",
                    "rows_non_empty",
                    "rows_have_filing_url",
                ],
            ),
            SemanticTest(
                name="form4_transaction_filter_applies",
                description="Filter transaction_types=['sell'] returns only sell rows.",
                inputs={"symbol": "AAPL", "transaction_types": ["sell"]},
                assertions=["all_rows_have_transaction_type_sell"],
            ),
            SemanticTest(
                name="form4_provider_outage_returns_unavailable",
                description="When EDGAR + yfinance both fail, status=provider_unavailable; no fake filings.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "rows_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["form4"]
