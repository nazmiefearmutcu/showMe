"""EE — Earnings & Estimates.

Historical quarterly EPS actual vs consensus + surprise % + next-period
estimate. Finnhub is the canonical (free-tier) source; yfinance fills in
calendar dates. Renders KPIs (last actual, last estimate, last surprise %,
beat rate) and a per-quarter table.
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
def ee() -> FunctionManifest:
    return FunctionManifest(
        code="EE",
        name="Earnings & Estimates",
        category=Category.EQUITIES,
        intent=(
            "Show historical quarterly EPS actuals vs consensus, the surprise %, beat rate, and "
            "the next-period estimate calendar date."
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
                name="history",
                label="History (quarters)",
                control=ControlKind.NUMBER,
                required=False,
                description="Quarters of actual-vs-estimate history to surface.",
                min=4,
                max=20,
                step=1,
                unit="quarters",
            ),
            InputSpec(
                name="live",
                label="Live mode",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true the handler calls Finnhub / yfinance live; otherwise a model template is used.",
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
            "history": 8,
            "live": True,
            "provider_mode": DataMode.DELAYED_REFERENCE.value,
        },
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
            must_have=["symbol", "status", "rows"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="period", label="Period", kind="text"),
                ColumnSpec(key="date", label="Date", kind="date"),
                ColumnSpec(key="actual", label="Actual", kind="number", format="%.4f"),
                ColumnSpec(key="estimate", label="Estimate", kind="number", format="%.4f"),
                ColumnSpec(key="surprisePercent", label="Surprise %", kind="percent", format="%.2f"),
            ],
            sortable=True,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="last_actual", label="Last actual", kind="big_number", unit="quote_ccy"),
                CardSlot(key="last_estimate", label="Last estimate", kind="kpi", unit="quote_ccy"),
                CardSlot(key="last_surprise_pct", label="Last surprise", kind="trend_pill", unit="%"),
                CardSlot(key="beat_rate", label="Beat rate", kind="kpi", unit="%"),
                CardSlot(key="next_earnings_date", label="Next earnings", kind="timestamp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "EE pulls historical actual-vs-estimate EPS for the last `history` quarters and the "
            "next-period estimate calendar from yfinance + finnhub. Surprise % is (actual − estimate) "
            "/ |estimate| × 100. Beat rate = count(actual > estimate) / count(rows) within the "
            "window. When live=false the panel returns a model template rather than calling upstream — "
            "this keeps the operator responsive during outages and is signalled via source_mode."
        ),
        formula_dict={
            "SurprisePct": Formula(
                expression=r"surprise\% = \frac{actual - estimate}{|estimate|} \times 100",
                variables={"actual": "Reported EPS", "estimate": "Consensus EPS estimate"},
            ),
            "BeatRate": Formula(
                expression=r"beat\_rate = \frac{|\{ t : actual_t > estimate_t \}|}{N} \times 100",
                variables={"N": "Number of historical periods"},
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Equity ticker.", source="instrument"),
            "rows": FieldDef(description="Per-quarter actual / estimate / surprise rows.", source="provider"),
            "last_actual": FieldDef(unit="quote_ccy", description="Most-recent reported EPS.", source="provider"),
            "last_estimate": FieldDef(unit="quote_ccy", description="Most-recent consensus estimate.", source="provider"),
            "last_surprise_pct": FieldDef(unit="%", description="Most-recent surprise %.", source="computed"),
            "beat_rate": FieldDef(unit="%", description="Percent of historical periods with actual > estimate.", source="computed"),
            "next_earnings_date": FieldDef(description="Next scheduled earnings date.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=False,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="ee_aapl_returns_quarterly_history",
                description="EE for AAPL returns history rows with actual/estimate fields.",
                inputs={"symbol": "AAPL", "history": 8, "live": True},
                assertions=[
                    "status_in_ok_set",
                    "rows_non_empty",
                    "rows_have_actual_and_estimate",
                ],
            ),
            SemanticTest(
                name="ee_beat_rate_between_0_and_100",
                description="Beat rate stays within [0,100] inclusive.",
                inputs={"symbol": "AAPL"},
                assertions=["beat_rate_between_0_and_100"],
            ),
            SemanticTest(
                name="ee_provider_outage_returns_unavailable",
                description="When yfinance + finnhub both fail, status=provider_unavailable; no fake EPS.",
                inputs={"symbol": "ZZZZZZ", "live": True},
                assertions=[
                    "status_equals_provider_unavailable",
                    "rows_is_empty_array",
                ],
            ),
        ],
    )


__all__ = ["ee"]
