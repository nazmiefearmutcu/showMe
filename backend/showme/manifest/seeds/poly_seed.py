"""POLY — Polymarket-style prediction markets.

POLY surfaces prediction-market prices on real-world events (elections,
policy, crypto milestones) from the KEYLESS public Polymarket Gamma
/markets endpoint. No credential is required; `data_mode='not_configured'`
is the explicit provider_unavailable state for a real network outage —
never a reason to fabricate mock probability curves.
"""
from __future__ import annotations

from ..enums import (
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
def poly() -> FunctionManifest:
    return FunctionManifest(
        code="POLY",
        name="Prediction Markets",
        category=Category.MISC,
        intent=(
            "Surface prediction-market prices on real-world events (elections, policy, "
            "crypto milestones) from the KEYLESS public Polymarket Gamma feed; declares "
            "provider_unavailable (data_mode='not_configured') only on a real network outage."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="query",
                label="Topic",
                control=ControlKind.TEXT,
                required=True,
                description="Free-text topic / event search.",
            ),
            InputSpec(
                name="status",
                label="Status",
                control=ControlKind.SELECT,
                required=True,
                description="Filter by market lifecycle state.",
                options=["open", "closed", "resolved", "all"],
            ),
            InputSpec(
                name="min_liquidity_usd",
                label="Min liquidity",
                control=ControlKind.NUMBER,
                required=False,
                description="Drop markets with reported liquidity below this floor.",
                min=0,
                step=1000,
            ),
        ],
        defaults={
            "status": "open",
            "min_liquidity_usd": 10_000,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.NOT_CONFIGURED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="market_id", label="ID", kind="text"),
                ColumnSpec(key="question", label="Question", kind="text"),
                ColumnSpec(key="outcome", label="Outcome", kind="tag"),
                ColumnSpec(key="price", label="Price", kind="number", format="%.3f"),
                ColumnSpec(key="implied_prob", label="Prob", kind="percent", format="%.1f"),
                ColumnSpec(key="liquidity_usd", label="Liquidity", kind="currency", format="%.0f"),
                ColumnSpec(key="end_date", label="Ends", kind="date"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="market_count", label="Markets", kind="kpi"),
                CardSlot(key="total_liquidity_usd", label="Liquidity", kind="kpi", unit="USD"),
                CardSlot(key="top_market", label="Top Market", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "POLY reads the keyless public Polymarket Gamma /markets endpoint — no credential "
            "is required. Rows are per-outcome with the on-chain mid price and the implied "
            "probability (price * 100), filtered by status and min_liquidity_usd. Live results "
            "carry data_mode='delayed_reference' (Gamma is delayed); an empty result is "
            "'cached_snapshot'. When the Gamma endpoint is unreachable POLY returns "
            "data_mode='not_configured' with rows=[] and a warning naming the network outage — "
            "no synthetic probability curves, no fabricated liquidity figures, no fake question "
            "text."
        ),
        field_dict={
            "data_mode": FieldDef(description="not_configured | cached_snapshot | delayed_reference.", source="envelope"),
            "rows[].question": FieldDef(description="Market question text.", source="polymarket"),
            "rows[].outcome": FieldDef(description="Outcome label (YES / NO / candidate).", source="polymarket"),
            "rows[].price": FieldDef(unit="USDC", description="On-chain mid price in [0, 1].", source="polymarket"),
            "rows[].implied_prob": FieldDef(unit="%", description="price * 100.", source="computed"),
            "rows[].liquidity_usd": FieldDef(unit="USD", description="Reported pool liquidity.", source="polymarket"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="poly_explicit_unavailable_when_not_configured",
                description="When the keyless Gamma endpoint is unreachable, POLY returns data_mode='not_configured', rows=[], and a warning naming the network outage — never a synthetic market.",
                inputs={"_env": "no_polymarket_key"},
                assertions=[
                    "data_mode_equals_not_configured",
                    "rows_is_empty_array",
                    "warning_mentions_not_configured",
                    "no_synthetic_market_rows",
                ],
            ),
            SemanticTest(
                name="poly_filter_status_open_excludes_closed",
                description="With status='open' every returned row has end_date in the future.",
                inputs={"query": "election", "status": "open"},
                assertions=["every_row_end_date_in_future"],
            ),
            SemanticTest(
                name="poly_implied_prob_matches_price",
                description="For every row, implied_prob == price * 100 within 1e-6 (no rounding drift on the contract).",
                inputs={"query": "election"},
                assertions=["implied_prob_equals_price_times_100"],
            ),
        ],
    )


__all__ = ["poly"]
