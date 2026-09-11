"""EE — Earnings & Estimates.

Historical quarterly EPS actual vs consensus (Finnhub `/stock/earnings`,
with Yahoo earnings-dates as the secondary calendar source), surprise %,
beat rate and the next report date. Live by default; `reference=true`
serves the labelled template. Resynced to the shipped handler
(``engine/functions/equity/ee.py``) by fix lane F14 — the previous seed
claimed yfinance as primary and an empty-array outage contract, while
the shipped handler emits a labelled placeholder row (pane folds
availability, F6).
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
            "Show historical quarterly EPS actuals vs consensus, the surprise %, beat rate, "
            "and the next-period estimate calendar date."
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
                name="reference",
                label="Reference template",
                control=ControlKind.BOOLEAN,
                required=False,
                description=(
                    "When true the handler serves the labelled modeled template instead "
                    "of calling Finnhub / yfinance."
                ),
            ),
        ],
        defaults={
            "history": 8,
            "reference": False,
        },
        provider_chain=ProviderChain(
            primary="finnhub",
            fallbacks=["yfinance", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=14400, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "rows", "methodology", "field_dictionary"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="period", label="Period", kind="text"),
                ColumnSpec(key="date", label="Date", kind="date"),
                ColumnSpec(key="actual", label="Actual", kind="number", format="%.4f"),
                ColumnSpec(key="estimate", label="Estimate", kind="number", format="%.4f"),
                ColumnSpec(key="surprisePercent", label="Surprise %", kind="percent", format="%.2f"),
                ColumnSpec(key="source_mode", label="Source", kind="tag"),
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
            "EE merges Finnhub historical earnings (primary) with Yahoo earnings-date "
            "tables (secondary) for the requested `history` quarters. Rows expose actual "
            "EPS, consensus estimate, surprise percent ((actual − estimate) / |estimate| "
            "× 100, recomputed when the provider omits it), and a source_mode per row. "
            "Beat rate = count(actual > estimate) / count(rows with actual and estimate) "
            "over the loaded window. Live by default; `reference=true` serves the "
            "labelled `earnings_calendar_model` template (status=reference_model, "
            "data_mode=modeled). When neither provider responds the handler returns "
            "status=ok with ONE explicitly labelled placeholder row "
            "(period='provider_unavailable', source_mode='earnings_calendar_unavailable'), "
            "metadata fallback=true / live=false and a warning — never reported EPS. "
            "The pane folds that placeholder into an unavailable state (F6)."
        ),
        formula_dict={
            "SurprisePct": Formula(
                expression=r"surprise\% = \frac{actual - estimate}{|estimate|} \times 100",
                variables={"actual": "Reported EPS", "estimate": "Consensus EPS estimate"},
            ),
            "BeatRate": Formula(
                expression=r"beat\_rate = \frac{|\{ t : actual_t > estimate_t \}|}{N} \times 100",
                variables={"N": "Number of quarters with both actual and estimate"},
            ),
        },
        field_dict={
            "rows[].period": FieldDef(description="Quarter label (or 'provider_unavailable' for the labelled placeholder).", source="finnhub"),
            "rows[].actual": FieldDef(unit="quote_ccy", description="Reported EPS.", source="provider"),
            "rows[].estimate": FieldDef(unit="quote_ccy", description="Consensus EPS estimate before report.", source="provider"),
            "rows[].surprisePercent": FieldDef(unit="%", description="(actual − estimate) / |estimate| × 100.", source="computed"),
            "rows[].source_mode": FieldDef(description="finnhub_earnings | yfinance_earnings_dates | earnings_calendar_unavailable.", source="provider"),
            "calendar": FieldDef(description="Next scheduled earnings date metadata from the yfinance calendar leg.", source="provider"),
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
                description="With a wired provider, EE returns history rows carrying actual/estimate fields.",
                inputs={"symbol": "AAPL", "history": 8},
                assertions=[
                    "status_equals_ok",
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
                name="ee_provider_outage_returns_labelled_placeholder_row",
                description=(
                    "When yfinance + finnhub both fail, status=ok with a single labelled "
                    "placeholder row (source_mode=earnings_calendar_unavailable) and "
                    "fallback metadata — never fake reported EPS and never an unlabelled "
                    "empty table."
                ),
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "rows_len_equals_1",
                    "placeholder_row_source_mode_is_earnings_calendar_unavailable",
                    "metadata_live_false",
                    "metadata_fallback_true",
                    "warning_non_empty",
                ],
            ),
        ],
    )


__all__ = ["ee"]
