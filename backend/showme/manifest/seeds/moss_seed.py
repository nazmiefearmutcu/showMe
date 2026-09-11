"""MOSS — Most Volatile (realised-volatility leaderboard).

Ranks a watchlist / universe by annualized realised volatility computed
from daily close history: ``std(close-to-close returns) * sqrt(252)``.
Live by default (yfinance); ``reference=true`` serves the explicitly
labelled modeled template. Resynced to the shipped handler
(``engine/functions/misc/_bonus.py::MOSSFunction``) by fix lane F14 —
the previous seed described an unimplemented "Sectoral Movers" contract.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
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
def moss() -> FunctionManifest:
    return FunctionManifest(
        code="MOSS",
        name="Most Volatile",
        category=Category.SCREENING,
        intent=(
            "Rank a universe by annualized realised volatility (std of daily close-to-close "
            "returns × sqrt(252)) so an operator can see which names are moving hardest; "
            "reference=true serves the labelled modeled template when live history is off."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.COMMODITY,
            AssetClass.FX,
        ],
        inputs=[
            InputSpec(
                name="universe",
                label="Universe",
                control=ControlKind.TEXT,
                required=False,
                description="Comma-separated symbols; defaults to the handler's liquid multi-asset sample.",
            ),
            InputSpec(
                name="days",
                label="Lookback (days)",
                control=ControlKind.NUMBER,
                required=False,
                description="Daily close-history window used for the realised-vol computation.",
                min=20,
                max=1095,
                step=1,
                unit="days",
            ),
            InputSpec(
                name="limit",
                label="Top N",
                control=ControlKind.NUMBER,
                required=False,
                description="Cap on returned ranked rows.",
                min=1,
                max=200,
                step=1,
            ),
            InputSpec(
                name="reference",
                label="Reference template",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "When true the handler serves the labelled modeled volatility "
                    "template instead of calling yfinance."
                ),
            ),
        ],
        defaults={"days": 90, "limit": 20, "reference": False},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.MODELED,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["status", "rows", "universe", "lookback_days", "data_mode", "live"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="%", label="Annualized vol"),
            y_axis=AxisSpec(type="category", unit="", label="Symbol"),
            panes=[],
            overlay_support=False,
            compare_support=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="symbol", label="Symbol", kind="text"),
                ColumnSpec(key="asset_class", label="Class", kind="tag"),
                ColumnSpec(key="vol_pct", label="Vol %", kind="percent", format="%.2f"),
                ColumnSpec(key="samples", label="Samples", kind="number", format="%d"),
                ColumnSpec(key="last_close", label="Last", kind="currency", format="%.2f"),
                ColumnSpec(key="start", label="Start", kind="date"),
                ColumnSpec(key="end", label="End", kind="date"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="top_symbol", label="Most volatile", kind="badge"),
                CardSlot(key="universe_size", label="Universe", kind="kpi"),
                CardSlot(key="lookback_days", label="Lookback", kind="kpi", unit="d"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="live", label="Live", kind="badge"),
            ],
        ),
        methodology=(
            "MOSS computes annualized realised volatility per symbol from daily closes: "
            "pct_change over the requested lookback, std(daily returns) * sqrt(252), ranked "
            "descending. The history series is the rolling realized volatility for the top "
            "symbol, using window = min(20, max(5, n//2)) sessions so short histories still "
            "produce a curve. The live path requires the yfinance provider; when it is "
            "unavailable the handler returns status=provider_unavailable with rows=[] and "
            "next_actions — never a fabricated ranking. reference=true serves the labeled "
            "volatility_model template (data_mode=modeled, live=false)."
        ),
        field_dict={
            "rows[].symbol": FieldDef(description="Instrument ticker.", source="universe"),
            "rows[].asset_class": FieldDef(description="Resolved asset class.", source="instrument"),
            "rows[].vol_annualized": FieldDef(description="Annualized realized volatility as a decimal.", source="computed"),
            "rows[].vol_pct": FieldDef(unit="%", description="Annualized realized volatility in percent.", source="computed"),
            "rows[].samples": FieldDef(description="Number of daily return observations used.", source="computed"),
            "rows[].last_close": FieldDef(unit="quote_ccy", description="Most recent daily close.", source="yfinance"),
            "history[].vol_pct": FieldDef(unit="%", description="Rolling-window annualized realized volatility for the top symbol.", source="computed"),
            "history[].window": FieldDef(description="Rolling window (sessions) actually used for the history series.", source="computed"),
            "lookback_days": FieldDef(unit="days", description="Requested daily close-history window.", source="input"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="moss_default_is_live_and_outage_is_labelled",
                description=(
                    "Default path attempts yfinance; when every symbol fails the payload is "
                    "status=provider_unavailable with empty rows and fallback metadata — "
                    "volatility is never fabricated."
                ),
                inputs={},
                assertions=[
                    "status_equals_provider_unavailable_when_no_provider",
                    "rows_is_empty_array_on_outage",
                    "metadata_live_false_on_outage",
                ],
            ),
            SemanticTest(
                name="moss_reference_template_never_claims_live",
                description=(
                    "reference=true serves the modeled template with data_mode=modeled, "
                    "live=false and an explicit volatility_model source label."
                ),
                inputs={"reference": True},
                assertions=[
                    "data_mode_equals_modeled",
                    "metadata_live_is_false",
                    "source_is_volatility_model",
                ],
            ),
            SemanticTest(
                name="moss_vol_pct_is_vol_times_100",
                description="vol_pct equals vol_annualized × 100 for every ranked row.",
                inputs={},
                assertions=["vol_pct_matches_vol_times_100"],
            ),
            SemanticTest(
                name="moss_history_carries_actual_window",
                description=(
                    "Every history row carries the rolling window actually used, so captions "
                    "can state the session count instead of hardcoding 20."
                ),
                inputs={},
                assertions=["history_rows_include_window_field"],
            ),
        ],
    )


__all__ = ["moss"]
