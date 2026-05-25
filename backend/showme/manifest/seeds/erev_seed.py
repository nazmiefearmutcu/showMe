"""EREV — Earnings Revisions.

Counts analyst upgrades / downgrades per month from finnhub recommendation
buckets, computes a 4-week revision velocity (net upgrades − downgrades),
and ranks revisions chronologically. Used to spot when consensus is moving
ahead of price.
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
            "Count analyst upgrades/downgrades per month and compute revision velocity so the "
            "operator can spot when consensus is moving ahead of price."
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
                description="Lookback for the revision history.",
                min=3,
                max=24,
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
        defaults={"months": 12, "provider_mode": DataMode.DELAYED_REFERENCE.value},
        provider_chain=ProviderChain(
            primary="yfinance",
            fallbacks=["finnhub", "cached_snapshot"],
            acceptable_modes=[
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
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
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="current_score_value", label="Avg score", kind="big_number"),
                CardSlot(key="velocity_avg", label="Velocity (4w)", kind="kpi"),
                CardSlot(key="net_upgrades", label="Net upgrades", kind="trend_pill"),
                CardSlot(key="analyst_count", label="Analysts", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "EREV reads finnhub recommendation_trends month-by-month for the lookback window. "
            "Each row's score is sum(weight × count) where strongBuy=+2, buy=+1, hold=0, sell=−1, "
            "strongSell=−2. The revisions table records per-month net change (upgrades minus "
            "downgrades, scoring deltas). Velocity is the trailing 4-week average of net positive "
            "minus net negative changes."
        ),
        formula_dict={
            "BucketScore": Formula(
                expression=r"score = 2 \cdot sb + 1 \cdot b + 0 \cdot h - 1 \cdot s - 2 \cdot ss",
                variables={"sb": "strongBuy", "b": "buy", "h": "hold", "s": "sell", "ss": "strongSell"},
                notes="Weighted analyst sentiment index.",
            ),
            "Velocity": Formula(
                expression=r"velocity = \frac{1}{4} \sum_{t=now-4w}^{now} (upgrades_t - downgrades_t)",
                variables={"upgrades_t": "Net positive bucket moves", "downgrades_t": "Net negative bucket moves"},
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "trend": FieldDef(description="Per-month bucket counts + weighted score.", source="finnhub"),
            "revisions": FieldDef(description="Per-month net upgrade / downgrade deltas.", source="computed"),
            "velocity_avg": FieldDef(description="4-week rolling revision velocity.", source="computed"),
            "current_score_value": FieldDef(description="Most-recent month's weighted score.", source="computed"),
            "analyst_count": FieldDef(description="Sum of bucket counts in the latest month.", source="finnhub"),
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
                description="EREV for AAPL returns at least one trend row + numeric velocity_avg.",
                inputs={"symbol": "AAPL", "months": 12},
                assertions=[
                    "status_in_ok_set",
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
                description="When finnhub is unreachable, status=provider_unavailable; no fake trend.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "status_equals_provider_unavailable",
                    "trend_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["erev"]
