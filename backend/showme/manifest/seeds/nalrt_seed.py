"""NALRT — Critical News Alerts (high-importance sourced stories).

Backend handler is ``engine/functions/news/nalrt.py``. A row qualifies when its awareness
importance score is at or above ``min_importance`` within ``hours``; severity is critical
at 85 and up, high otherwise. The alert engine reads the same handler.
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
    AlertingSpec,
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
def nalrt() -> FunctionManifest:
    return FunctionManifest(
        code="NALRT",
        name="News Alerts Center",
        category=Category.NEWS_INTEL,
        intent=(
            "Stories whose awareness importance clears a floor within a recent window, graded "
            "critical or high, each with publisher, sentiment and a link to the source article."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.CRYPTO,
            AssetClass.ETF,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="hours",
                label="Window (hours)",
                control=ControlKind.NUMBER,
                required=False,
                description="Look-back window in hours (1 to 168).",
                min=1.0,
                max=168.0,
                step=1.0,
                unit="hours",
            ),
            InputSpec(
                name="min_importance",
                label="Min importance",
                control=ControlKind.NUMBER,
                required=False,
                description="Awareness importance floor on the 0-100 scale; stories at or above it qualify.",
                min=0.0,
                max=100.0,
                step=1.0,
            ),
            InputSpec(
                name="limit",
                label="Rows",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum number of alert rows (1 to 200).",
                min=1.0,
                max=200.0,
                step=1.0,
            ),
        ],
        defaults={"hours": 6, "min_importance": 70, "limit": 30},
        provider_chain=ProviderChain(
            primary="awareness",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["status", "rows", "alerts", "meta"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="published_at", label="Published", kind="datetime", format="rel-time"),
                ColumnSpec(key="severity", label="Severity", kind="tag"),
                ColumnSpec(key="publisher", label="Source", kind="tag"),
                ColumnSpec(key="title", label="Headline", kind="text"),
                ColumnSpec(key="symbols", label="Symbols", kind="tag"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="importance", label="Importance", kind="number", format="%.0f"),
                ColumnSpec(key="url", label="Article", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="alert_count", label="Alerts", kind="kpi"),
                CardSlot(key="critical_count", label="Critical", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "NALRT reads the awareness news stream collapsed to stories at quality standard or "
            "better, keeps the stories whose importance score (0-100, awareness) is at or above "
            "min_importance within the hours window, and grades them: critical at importance 85 "
            "and up, high otherwise. Each row is a real publisher article with its title, "
            "publisher, timestamp, FinBERT sentiment and link. Nothing is synthesised: when no "
            "story clears the floor the response is empty, and when awareness is unreachable it "
            "is provider_unavailable."
        ),
        field_dict={
            "rows[].published_at": FieldDef(unit="iso8601", description="Publisher timestamp (UTC).", source="feed"),
            "rows[].severity": FieldDef(description="critical (importance >= 85) or high.", source="computed"),
            "rows[].publisher": FieldDef(description="Publisher name.", source="feed"),
            "rows[].title": FieldDef(description="Headline verbatim from the publisher.", source="feed"),
            "rows[].url": FieldDef(unit="url", description="Link to the publisher article.", source="feed"),
            "rows[].sentiment": FieldDef(description="positive, negative or neutral (FinBERT label).", source="finbert"),
            "rows[].importance": FieldDef(unit="0-100", description="Awareness importance score.", source="awareness"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["importance_at_or_above_min_importance"],
            delivery=["tray", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="nalrt_fire_links_to_real_article",
                description="Every alert row has a non-empty url and a headline verbatim from the publisher.",
                inputs={"min_importance": 70},
                assertions=["every_row_has_url", "title_is_publisher_headline"],
            ),
            SemanticTest(
                name="nalrt_severity_grades_by_importance",
                description="Rows with importance >= 85 are critical; rows between min_importance and 85 are high.",
                inputs={"min_importance": 70},
                assertions=["critical_iff_importance_at_least_85"],
            ),
            SemanticTest(
                name="nalrt_no_synthetic_alerts",
                description="When no story clears min_importance, rows is empty and status is empty.",
                inputs={"min_importance": 100},
                assertions=["rows_empty_when_no_story_clears_floor"],
            ),
        ],
    )


__all__ = ["nalrt"]
