"""TOP — Top News (sourced story leads from the Awareness news service).

Backend handler is ``engine/functions/news/top.py``. Rows are awareness story
leads at quality >= standard, read through ``GET /v1/markets/news?story=true``.
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
def top() -> FunctionManifest:
    return FunctionManifest(
        code="TOP",
        name="Top News",
        category=Category.NEWS_INTEL,
        intent=(
            "Surface the sourced stories that matter right now across asset classes: one row per "
            "story at quality standard or better, ranked by awareness importance, with publisher "
            "tier, quality reasons, FinBERT sentiment and corroboration."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.RATE,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="hours",
                label="Window (hours)",
                control=ControlKind.NUMBER,
                required=False,
                description="Look-back window in hours for story leads (1 to 168).",
                min=1.0,
                max=168.0,
                step=1.0,
                unit="hours",
            ),
            InputSpec(
                name="limit",
                label="Rows",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum number of story rows (1 to 200).",
                min=1.0,
                max=200.0,
                step=1.0,
            ),
            InputSpec(
                name="min_quality",
                label="Quality floor",
                control=ControlKind.SELECT,
                required=False,
                description="Lowest awareness quality label kept: premium, or standard and above. Low-quality news is never shown on TOP; a requested low is clamped to standard with a warning.",
                options=["premium", "standard"],
            ),
            InputSpec(
                name="topics",
                label="Topics",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Awareness taxonomy topics; a story matches when it carries any of them.",
                options=[
                    "earnings", "guidance", "m_and_a", "ipo", "dividends_buybacks", "analyst_rating",
                    "central_bank", "inflation", "employment", "growth_recession", "trade_tariffs",
                    "sanctions", "geopolitics", "regulation", "energy", "metals", "crypto_market",
                    "supply_chain", "cyber_outage", "fiscal_policy",
                ],
            ),
            InputSpec(
                name="asset_classes",
                label="Asset classes",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Awareness asset-class tags; combined with topics by AND.",
                options=["equities", "indices", "fx", "rates", "credit", "commodities", "crypto", "macro"],
            ),
            InputSpec(
                name="countries",
                label="Countries",
                control=ControlKind.TEXT,
                required=False,
                description="Comma-separated ISO-2 country codes (for example US,TR).",
            ),
            InputSpec(
                name="q",
                label="Search",
                control=ControlKind.TEXT,
                required=False,
                description="Optional full-text search over titles and summaries.",
            ),
        ],
        defaults={
            "hours": 24,
            "limit": 50,
            "min_quality": "standard",
            "topics": [],
            "asset_classes": [],
            "countries": "",
            "q": "",
        },
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
            must_have=["status", "rows", "meta"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="published_at", label="Time", kind="datetime", format="rel-time"),
                ColumnSpec(key="publisher", label="Publisher", kind="tag"),
                ColumnSpec(key="publisher_tier", label="Tier", kind="number", format="%d"),
                ColumnSpec(key="title", label="Headline", kind="text"),
                ColumnSpec(key="symbols", label="Symbols", kind="tag"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="importance", label="Importance", kind="number", format="%.0f"),
                ColumnSpec(key="story_size", label="Sources", kind="number", format="%d"),
                ColumnSpec(key="url", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="count", label="Stories", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "Awareness (awareness-markets, local service) ingests keyless publisher feeds, scores "
            "each item with a quality gate (publisher tier, timestamp precision, entity confidence "
            "and topic evidence, reported as quality_reasons), labels sentiment per row (the row's "
            "sentiment_model names FinBERT ProsusAI/finbert or the lexicon fallback aw-fin-1), "
            "scores importance 0-100, and clusters near-duplicate reports into "
            "stories. TOP lists one lead per story at quality standard or better, newest first "
            "within the hours window; story_size counts the collapsed reports. Stale providers keep "
            "their data and mark the response cached_snapshot with live false."
        ),
        field_dict={
            "rows[].published_at": FieldDef(unit="iso8601", description="Publisher timestamp (UTC).", source="feed"),
            "rows[].publisher": FieldDef(description="Publisher name as registered in awareness.", source="feed"),
            "rows[].publisher_tier": FieldDef(unit="1-5", description="Publisher trust tier (1 is highest).", source="awareness"),
            "rows[].title": FieldDef(description="Headline as published.", source="feed"),
            "rows[].url": FieldDef(unit="url", description="Link to the publisher article.", source="feed"),
            "rows[].sentiment": FieldDef(description="positive, negative or neutral (awareness label; model named in sentiment_model).", source="finbert"),
            "rows[].sentiment_score": FieldDef(unit="[-1,1]", description="Signed sentiment score from the model named in sentiment_model.", source="finbert"),
            "rows[].importance": FieldDef(unit="0-100", description="Awareness importance score.", source="awareness"),
            "rows[].quality_label": FieldDef(description="premium, standard, low or rejected.", source="awareness"),
            "rows[].quality_reasons": FieldDef(description="Quality gate reasons, for example tier1:+45.", source="awareness"),
            "rows[].story_size": FieldDef(unit="count", description="Reports collapsed into this story.", source="awareness"),
            "rows[].story_id": FieldDef(description="Story identifier for the drawer.", source="awareness"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        semantic_tests=[
            SemanticTest(
                name="top_rows_are_story_leads_at_standard_quality",
                description="Every row is a story lead whose quality_label is premium or standard.",
                inputs={"hours": 24, "min_quality": "standard"},
                assertions=["every_row_quality_at_least_standard", "one_row_per_story_id"],
            ),
            SemanticTest(
                name="top_rows_within_hours_window",
                description="Every row's published_at lies inside the requested hours window.",
                inputs={"hours": 6},
                assertions=["all_rows_published_within_hours"],
            ),
            SemanticTest(
                name="top_no_rss_or_model_rows_when_awareness_down",
                description="When awareness is unreachable, rows is empty and status is provider_unavailable with the client reason.",
                inputs={},
                assertions=["rows_empty_when_unavailable", "status_provider_unavailable"],
            ),
            SemanticTest(
                name="top_stale_provider_marks_cached_snapshot",
                description="A down or degraded awareness provider keeps the rows but sets data_mode cached_snapshot and live false.",
                inputs={},
                assertions=["data_mode_cached_snapshot_when_stale", "live_false_when_stale"],
            ),
        ],
    )


__all__ = ["top"]
