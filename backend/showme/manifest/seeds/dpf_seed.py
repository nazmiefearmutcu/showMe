"""DPF — Dark Pool / ATS Volume.

FINRA OTC Transparency (ATS / off-exchange weekly share volume) is the
primary source. Dark-pool % is ATS volume divided by the REAL consolidated
weekly volume from yfinance for the same week; when that denominator is
missing the ratio is left null, never estimated. Matches the handler in
``engine/functions/equity/dpf.py`` (name "Dark Pool / ATS Volume").
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
def dpf() -> FunctionManifest:
    return FunctionManifest(
        code="DPF",
        name="Dark Pool / ATS Volume",
        category=Category.EQUITIES,
        intent=(
            "Show weekly FINRA-reported off-exchange (ATS) share volume for one equity and the "
            "dark-pool percentage of its real consolidated weekly volume."
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
                name="weeks",
                label="Weeks of history",
                control=ControlKind.NUMBER,
                required=False,
                description="How many weekly ATS aggregates to surface.",
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
        defaults={"weeks": 12, "provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="finra",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
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
                ColumnSpec(key="weekStartDate", label="Week", kind="date"),
                ColumnSpec(key="venue", label="Venue", kind="text"),
                ColumnSpec(key="ats_share_volume", label="ATS shares", kind="number", format="%.0f"),
                ColumnSpec(key="estimated_total_volume", label="Total shares (yfinance)", kind="number", format="%.0f"),
                ColumnSpec(key="dark_pool_pct", label="Dark pool (%)", kind="number", format="%.2f"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="latest_dark_pool_pct", label="Dark pool (%)", kind="big_number", unit="%"),
                CardSlot(key="latest_ats_volume", label="ATS shares", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "DPF reads FINRA OTC Transparency weekly ATS / off-exchange share volume for the "
            "symbol. dark_pool_pct = 100 x ATS share volume / real consolidated weekly volume "
            "from yfinance for the same week. When the real total volume is unavailable for a "
            "week, dark_pool_pct and estimated_total_volume are null rather than estimated. Every "
            "returned row is a FINRA weekly aggregate. When FINRA returns no rows (or fails), the "
            "result is provider_unavailable with a reason and an empty row set; no shape-model or "
            "synthetic rows are generated. A stale FINRA snapshot is labelled provider_unavailable."
        ),
        field_dict={
            "symbol": FieldDef(description="Equity or ETF ticker.", source="instrument"),
            "weekStartDate": FieldDef(description="ISO date of the Monday starting the reporting week.", source="provider"),
            "venue": FieldDef(description="ATS / MPID venue reported by FINRA.", source="provider"),
            "ats_share_volume": FieldDef(description="Off-exchange (ATS) shares FINRA reported for the symbol that week; empty rows (not estimates) when FINRA returns nothing.", source="provider"),
            "estimated_total_volume": FieldDef(description="Real consolidated weekly share volume (yfinance); null when unavailable.", source="provider"),
            "dark_pool_pct": FieldDef(description="ATS share of the real weekly total volume, in percent (0-100).", source="computed"),
            "source_mode": FieldDef(description="Live FINRA weekly row (finra_ats_weekly) or a stale FINRA row (finra_ats_weekly_stale); no fallback rows exist.", source="provider"),
            "rows": FieldDef(description="Weekly ATS rows, most recent first.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="dpf_dark_pool_pct_null_without_real_total_volume",
                description="When the yfinance weekly denominator is unavailable, dark_pool_pct is null, not estimated.",
                inputs={"symbol": "ZZZZZZ", "weeks": 4},
                assertions=[
                    "dark_pool_pct_null_without_real_total_volume",
                    "no_estimated_total_volume_without_denominator",
                ],
            ),
            SemanticTest(
                name="dpf_no_rows_without_finra",
                description="Without FINRA rows, DPF returns provider_unavailable with an empty row set; no generated rows carry a dark-pool ratio.",
                inputs={"symbol": "AAPL", "weeks": 8},
                assertions=[
                    "status_in_ok_or_provider_unavailable",
                    "rows_empty_without_finra",
                ],
            ),
        ],
    )


__all__ = ["dpf"]
