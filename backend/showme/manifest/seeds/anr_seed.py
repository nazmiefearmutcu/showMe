"""ANR — Analyst Recommendations + Price Target.

yfinance recommendations bucket history + analyst price target consensus,
with finnhub as fallback. Returns trend rows (period -> bucket counts +
weighted score) plus a headline price-target dict.
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
def anr() -> FunctionManifest:
    return FunctionManifest(
        code="ANR",
        name="Analyst Recommendations",
        category=Category.EQUITIES,
        intent=(
            "Show analyst recommendation buckets over time (Strong Buy → Strong Sell) plus "
            "the headline price-target consensus for a single equity."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker (AAPL, MSFT).",
            ),
            InputSpec(
                name="months",
                label="History (months)",
                control=ControlKind.NUMBER,
                required=False,
                description="Lookback window for the bucket trend table.",
                min=3,
                max=36,
                step=1,
                unit="months",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "months": 12,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["finnhub", "sec_edgar", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=21600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "trend", "current_score"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="period", label="Period", kind="date"),
                ColumnSpec(key="strongBuy", label="Str. Buy", kind="number"),
                ColumnSpec(key="buy", label="Buy", kind="number"),
                ColumnSpec(key="hold", label="Hold", kind="number"),
                ColumnSpec(key="sell", label="Sell", kind="number"),
                ColumnSpec(key="strongSell", label="Str. Sell", kind="number"),
                ColumnSpec(key="score", label="Score", kind="number", format="%.2f"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="current_score", label="Avg score", kind="big_number"),
                CardSlot(key="analyst_count", label="Analysts", kind="kpi"),
                CardSlot(key="price_target_mean", label="PT mean", kind="kpi", unit="quote_ccy"),
                CardSlot(key="price_target_high", label="PT high", kind="kpi", unit="quote_ccy"),
                CardSlot(key="price_target_low", label="PT low", kind="kpi", unit="quote_ccy"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "ANR fetches yfinance's recommendations DataFrame (per-month bucket counts) and "
            "the analyst price-target dict in parallel. Each row's score is a weighted average "
            "where strongBuy=5..strongSell=1. When yfinance has no rows, the chain falls back "
            "to finnhub recommendation_trends and price_target endpoints. The pane displays the "
            "latest month as the headline plus a `months`-long history table."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "trend": FieldDef(description="Per-period bucket counts + weighted score.", source="provider"),
            "current_score": FieldDef(description="Most-recent row of trend.", source="computed"),
            "price_target_mean": FieldDef(unit="quote_ccy", description="Consensus mean price target.", source="provider"),
            "price_target_high": FieldDef(unit="quote_ccy", description="High end of analyst price targets.", source="provider"),
            "price_target_low": FieldDef(unit="quote_ccy", description="Low end of analyst price targets.", source="provider"),
            "analyst_count": FieldDef(description="Number of analysts covering the latest period.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="anr_aapl_returns_bucket_trend",
                description="ANR for AAPL returns non-empty trend rows with weighted score per period.",
                inputs={"symbol": "AAPL", "months": 12},
                assertions=[
                    "status_in_ok_set",
                    "trend_non_empty",
                    "current_score_present",
                    "trend_row_has_bucket_counts",
                ],
            ),
            SemanticTest(
                name="anr_price_target_dict_populated",
                description="ANR exposes consensus price-target mean/high/low when the provider returns them.",
                inputs={"symbol": "MSFT"},
                assertions=[
                    "price_target_mean_is_positive_number_or_null",
                ],
            ),
            SemanticTest(
                name="anr_provider_outage_returns_unavailable_not_synthetic",
                description="When yfinance + finnhub both fail, status=provider_unavailable with next_actions.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "trend_is_empty_array",
                    "next_actions_non_empty",
                ],
            ),
        ],
    )


__all__ = ["anr"]
