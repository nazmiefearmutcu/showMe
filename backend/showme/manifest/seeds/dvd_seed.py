"""DVD — Dividends & Splits.

yfinance corporate-action stream merged into a single typed action list
(dividend cash amounts + split ratios). SEC EDGAR is the fallback for the
authoritative dividend declaration filings. Renders as KPIs (last dividend,
yield proxy, counts) + chronological table.
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
def dvd() -> FunctionManifest:
    return FunctionManifest(
        code="DVD",
        name="Dividends & Splits",
        category=Category.EQUITIES,
        intent=(
            "List historical cash dividends and stock splits with the latest dividend, an "
            "approximate trailing yield, and the per-event audit trail."
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
                name="live",
                label="Live mode",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true the handler calls yfinance live; otherwise a model template is used.",
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
        defaults={"live": True, "provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["sec_edgar", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=14400, scope="per_input", persist=True),
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
                ColumnSpec(key="date", label="Date", kind="date"),
                ColumnSpec(key="action_type", label="Type", kind="tag"),
                ColumnSpec(key="amount", label="Amount", kind="number", format="%.4f"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="last_dividend", label="Last dividend", kind="big_number", unit="quote_ccy"),
                CardSlot(key="trailing_yield", label="Yield (proxy)", kind="kpi", unit="%"),
                CardSlot(key="dividend_count", label="Div events", kind="kpi"),
                CardSlot(key="split_count", label="Splits", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DVD reads yfinance's actions DataFrame and emits a typed list of {date, action_type, "
            "amount, source_mode}. Dividends are reported per share in the quote currency; splits "
            "as the ratio (e.g. 4 for a 4:1 split). Trailing yield is amount-summed dividends in "
            "the last 365 days divided by the latest price snapshot. When live=false the handler "
            "returns the model template rather than calling yfinance — this keeps the panel "
            "responsive during outages and is reported via source_mode."
        ),
        formula_dict={
            "TrailingYield": Formula(
                expression=r"yield \approx \frac{\sum_{t \in 365d} D_t}{P_{latest}}",
                variables={"D_t": "Cash dividend per share", "P_latest": "Most-recent close"},
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "rows": FieldDef(description="Chronological list of dividends and splits.", source="provider"),
            "last_dividend": FieldDef(unit="quote_ccy", description="Most-recent cash dividend per share.", source="provider"),
            "trailing_yield": FieldDef(unit="%", description="Sum of dividends in the last 365d / latest price.", source="computed"),
            "dividend_count": FieldDef(description="Count of dividend rows in history.", source="computed"),
            "split_count": FieldDef(description="Count of split rows in history.", source="computed"),
            "source_mode": FieldDef(description="live | model | cached.", source="envelope"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="dvd_aapl_returns_dividend_history",
                description="DVD for AAPL returns at least one dividend row + a positive last_dividend.",
                inputs={"symbol": "AAPL", "live": True},
                assertions=[
                    "status_in_ok_set",
                    "rows_non_empty",
                    "last_dividend_is_positive_number",
                ],
            ),
            SemanticTest(
                name="dvd_model_mode_does_not_call_live_provider",
                description="With live=false the handler does not call yfinance live; source_mode=model.",
                inputs={"symbol": "AAPL", "live": False},
                assertions=[
                    "source_mode_equals_model",
                ],
            ),
            SemanticTest(
                name="dvd_provider_outage_returns_unavailable",
                description="When yfinance + SEC both fail, status=provider_unavailable; no fake dividends.",
                inputs={"symbol": "ZZZZZZ", "live": True},
                assertions=[
                    "status_equals_provider_unavailable",
                    "rows_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["dvd"]
