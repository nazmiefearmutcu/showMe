"""DARK — Dark pool / off-exchange ATS prints.

FINRA ATS Transparency is the canonical source for weekly off-exchange
share volume by venue; the handler aggregates per-venue prints into a
single weekly ranking. yfinance volumes provide the lit-market baseline
for the dark-pool % calculation when FINRA is unavailable.
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
def dark() -> FunctionManifest:
    return FunctionManifest(
        code="DARK",
        name="Dark Pool Prints",
        category=Category.EQUITIES,
        intent=(
            "Show off-exchange ATS volume per venue plus the rolling dark-pool % of total "
            "volume so the operator can see where liquidity is fragmenting."
        ),
        asset_classes=[AssetClass.EQUITY, AssetClass.ETF],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker.",
            ),
            InputSpec(
                name="weeks",
                label="Weeks of history",
                control=ControlKind.NUMBER,
                required=False,
                description="How many weekly aggregates to surface.",
                min=2,
                max=26,
                step=1,
                unit="weeks",
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
        defaults={"weeks": 8, "provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["finra", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=14400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "venues"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="venue", label="Venue", kind="text"),
                ColumnSpec(key="ats_share_volume", label="ATS volume", kind="number", format="%.0f"),
                ColumnSpec(key="ats_trade_count", label="Trades", kind="number"),
                ColumnSpec(key="dark_pool_pct", label="Dark pool %", kind="percent", format="%.2f"),
                ColumnSpec(key="weekStartDate", label="Week", kind="date"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="latest_dark_pool_pct", label="Dark pool %", kind="big_number", unit="%"),
                CardSlot(key="latest_ats_volume", label="ATS vol", kind="kpi"),
                CardSlot(key="venue_count", label="Venues", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DARK pulls FINRA ATS Transparency weekly aggregates (volume + trade count per venue) "
            "and joins them against yfinance total weekly volume. Dark-pool % = ATS volume / lit + "
            "ATS volume per week. The handler ranks venues by ATS volume within the most recent "
            "week so the operator can see who is providing the off-exchange liquidity. When FINRA "
            "is unreachable the chain falls back to a model that estimates dark-pool % from "
            "off-exchange yfinance volume buckets, and warns about the fallback."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "venues": FieldDef(description="Per-venue weekly ATS aggregates.", source="finra"),
            "latest_dark_pool_pct": FieldDef(unit="%", description="Most-recent week's dark-pool ratio.", source="computed"),
            "latest_ats_volume": FieldDef(description="Most-recent week's ATS share volume.", source="finra"),
            "venue_count": FieldDef(description="Distinct ATS venues in the latest week.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="dark_aapl_returns_weekly_venues",
                description="DARK for AAPL returns weekly per-venue rows with computed dark-pool %.",
                inputs={"symbol": "AAPL", "weeks": 8},
                assertions=[
                    "status_in_ok_set",
                    "venues_non_empty",
                    "latest_dark_pool_pct_between_0_and_100",
                ],
            ),
            SemanticTest(
                name="dark_provider_outage_returns_unavailable",
                description="When FINRA + yfinance both fail, status=provider_unavailable; no fake venues.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "venues_is_empty_array",
                    "next_actions_non_empty",
                ],
            ),
        ],
    )


__all__ = ["dark"]
