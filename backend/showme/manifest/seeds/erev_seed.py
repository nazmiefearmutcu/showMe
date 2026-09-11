"""EREV — Earnings Revisions.

Converts Finnhub analyst recommendation buckets (`/stock/recommendation`)
into a weighted per-period score (Strong Buy=+2 … Strong Sell=−2),
computes the net upgrade/downgrade deltas per period, and reports the
latest average-score change as revision velocity. Resynced to the
shipped handler (``engine/functions/equity/erev.py``) by fix lane F14 —
the previous seed claimed a yfinance primary and a 4-week rolling
velocity the handler never implemented.
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
def erev() -> FunctionManifest:
    return FunctionManifest(
        code="EREV",
        name="Earnings Revisions",
        category=Category.EQUITIES,
        intent=(
            "Score analyst recommendation buckets per period and compute the revision "
            "velocity so the operator can spot when consensus is moving ahead of price."
        ),
        asset_classes=[AssetClass.EQUITY],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker whose Finnhub recommendation buckets to score.",
            ),
        ],
        defaults={},
        provider_chain=ProviderChain(
            primary="finnhub",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.NOT_CONFIGURED,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=14400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "trend", "revisions", "velocity_avg"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="period", label="Month", kind="date"),
                ColumnSpec(key="strongBuy", label="Str. Buy", kind="number"),
                ColumnSpec(key="buy", label="Buy", kind="number"),
                ColumnSpec(key="hold", label="Hold", kind="number"),
                ColumnSpec(key="sell", label="Sell", kind="number"),
                ColumnSpec(key="strongSell", label="Str. Sell", kind="number"),
                ColumnSpec(key="score", label="Score", kind="number", format="%.2f"),
                ColumnSpec(key="avg", label="Avg", kind="number", format="%.4f"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="velocity_avg", label="Velocity", kind="big_number"),
                CardSlot(key="current_score", label="Current", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "EREV reads Finnhub analyst recommendation buckets (strongBuy/buy/hold/sell/"
            "strongSell per period), sorts them oldest → newest, and converts each period "
            "to a weighted score: strongBuy=+2, buy=+1, hold=0, sell=−1, strongSell=−2 "
            "(avg = score / analyst count). Revisions are the period-over-period deltas "
            "(net_pos_change = Δ(strongBuy+buy), net_neg_change = Δ(sell+strongSell), "
            "delta_avg = period avg − prior avg). Velocity is the latest average-score "
            "change versus the prior period. When Finnhub is absent or returns no buckets "
            "for the symbol, the handler returns status=provider_unavailable with empty "
            "trend/revisions and a reason — it never substitutes hard-coded buckets."
        ),
        formula_dict={
            "BucketScore": Formula(
                expression=r"score = 2 \cdot sb + 1 \cdot b + 0 \cdot h - 1 \cdot s - 2 \cdot ss",
                variables={"sb": "strongBuy", "b": "buy", "h": "hold", "s": "sell", "ss": "strongSell"},
                notes="Weighted analyst sentiment index per period.",
            ),
            "Average": Formula(
                expression=r"avg = score / n, \quad n = sb + b + h + s + ss",
                variables={},
            ),
            "Velocity": Formula(
                expression=r"velocity = avg_{latest} - avg_{previous}",
                variables={},
                notes="Approximated from the two most recent periods in the bucket series.",
            ),
        },
        field_dict={
            "trend[].score": FieldDef(description="Weighted recommendation score for the period.", source="finnhub"),
            "trend[].avg": FieldDef(description="Score divided by analyst count.", source="computed"),
            "revisions[].net_pos_change": FieldDef(description="Change in Strong Buy + Buy count vs prior period.", source="computed"),
            "revisions[].net_neg_change": FieldDef(description="Change in Sell + Strong Sell count vs prior period.", source="computed"),
            "velocity_avg": FieldDef(description="Latest average-score change vs previous period.", source="computed"),
            "current_score": FieldDef(description="Most recent period's bucket row.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="erev_aapl_returns_trend_and_velocity",
                description="With a wired Finnhub provider, EREV returns trend rows and a numeric velocity_avg.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "status_equals_ok",
                    "trend_non_empty",
                    "velocity_avg_is_finite_number",
                ],
            ),
            SemanticTest(
                name="erev_bucket_score_weighted_per_formula",
                description="The score column equals 2*sb + b - s - 2*ss (within numeric tolerance).",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "score_matches_weighted_formula_within_1e-6",
                ],
            ),
            SemanticTest(
                name="erev_provider_outage_returns_unavailable",
                description="When Finnhub is absent or errors, status=provider_unavailable with empty trend/revisions and no fake buckets.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "trend_is_empty_array",
                    "revisions_is_empty_array",
                    "sources_is_empty_list",
                ],
            ),
        ],
    )


__all__ = ["erev"]
