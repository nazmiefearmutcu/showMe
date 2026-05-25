"""TOP — Top News (cross-asset, freshness-aware, deduped, impact-scored).

Live top-news pane that surfaces what's actually moving markets right
now across all asset classes. Backend handler is
``engine/functions/news/top.py`` which runs a unified RSS + GDELT
pipeline with NER-lite ticker tagging, FinBERT-derived sentiment, and
SimHash dedupe.
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
def top() -> FunctionManifest:
    return FunctionManifest(
        code="TOP",
        name="Top News",
        category=Category.NEWS_INTEL,
        intent=(
            "Surface what is actually moving markets right now across all asset classes with "
            "deduplication, freshness windows, source provenance, optional sentiment/impact scoring, "
            "and one-click drilldowns into CN/DES/GP per ticker."
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
                name="freshness",
                label="Freshness",
                control=ControlKind.SELECT,
                required=True,
                description="Max age of items to surface.",
                options=["15m", "1h", "6h", "24h", "7d"],
            ),
            InputSpec(
                name="asset_filter",
                label="Asset classes",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to items tagged with these asset classes.",
                options=[
                    "equity", "crypto", "fx", "commodity",
                    "bond", "rate", "macro",
                ],
            ),
            InputSpec(
                name="topic_filter",
                label="Topics",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to editorial topic tags.",
                options=[
                    "earnings", "m&a", "central_bank",
                    "geopolitics", "regulatory", "macro",
                    "crypto_protocol",
                ],
            ),
            InputSpec(
                name="min_impact",
                label="Min impact",
                control=ControlKind.SELECT,
                required=False,
                description="Drop items with computed impact below this floor.",
                options=["low", "medium", "high"],
            ),
            InputSpec(
                name="dedupe",
                label="Dedupe similar",
                control=ControlKind.BOOLEAN,
                required=True,
                description="Cluster near-duplicate stories via SimHash.",
            ),
            InputSpec(
                name="sentiment_overlay",
                label="Sentiment",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Show FinBERT pos/neu/neg labels in each row.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred provider mode; chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.DELAYED_REFERENCE.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "freshness": "6h",
            "asset_filter": [],
            "topic_filter": [],
            "min_impact": "low",
            "dedupe": True,
            "sentiment_overlay": True,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        # Real handler defaults source_order to ["rss"] and optionally
        # adds gdelt on deep=True — but the spec's design treats GDELT
        # as the canonical primary, so manifest-time chain order reflects
        # the spec (rss is fallback when GDELT rate-limits).
        provider_chain=ProviderChain(
            primary="gdelt",
            fallbacks=["rss", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["as_of", "items", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="published_utc", label="Time", kind="datetime", format="rel-time"),
                ColumnSpec(key="source", label="Source", kind="tag"),
                ColumnSpec(key="title", label="Title", kind="text"),
                ColumnSpec(key="tickers", label="Tickers", kind="tag"),
                ColumnSpec(key="asset_class", label="Class", kind="tag"),
                ColumnSpec(key="topic", label="Topic", kind="tag"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="sentiment_score", label="Score", kind="number", format="%.2f"),
                ColumnSpec(key="impact", label="Impact", kind="tag"),
                ColumnSpec(key="dedupe_cluster_size", label="Dup ×", kind="number", format="%d"),
                ColumnSpec(key="link", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_items", label="Total", kind="kpi"),
                CardSlot(key="high_impact_count", label="High Impact", kind="kpi"),
                CardSlot(key="sources_active", label="Sources", kind="kpi"),
                CardSlot(key="top_topic", label="Top Topic", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TOP runs a unified ingestion pipeline: GDELT DOC search with a top-domain whitelist plus "
            "parallel RSS pulls from a curated list of official + reputable financial sources, then "
            "normalize each item to {published_utc, source, title, body_snippet, url, raw_tickers, "
            "raw_topics}. Tickers are tagged via a fast NER-lite (regex + cashtag + symbol dictionary in "
            "DuckDB); asset class via the symbol->asset_class map (OpenFIGI for ambiguous cases); topic "
            "via a keyword classifier; sentiment via FinBERT (label + score). Impact is a heuristic that "
            "combines source authority, topic weight, sentiment magnitude, and freshness decay. SimHash "
            "(4-shingle on title) plus a URL-domain check collapse near-duplicates into a single "
            "representative item with dedupe_cluster_size. Items older than the freshness input are "
            "dropped; remaining items are sorted by published_utc desc (impact tie-break). No item is "
            "ever surfaced without a verifiable source URL."
        ),
        field_dict={
            "items[].published_utc": FieldDef(unit="iso8601", description="Original publication time.", source="feed"),
            "items[].source": FieldDef(description="Source domain (e.g. reuters.com).", source="derived"),
            "items[].title": FieldDef(description="Article headline.", source="feed"),
            "items[].tickers": FieldDef(description="Detected canonical tickers; empty when uncertain.", source="ner"),
            "items[].asset_class": FieldDef(description="Tagged asset class.", source="symbol_map"),
            "items[].topic": FieldDef(description="Editorial topic tag.", source="classifier"),
            "items[].sentiment": FieldDef(description="FinBERT pos/neu/neg label.", source="finbert"),
            "items[].sentiment_score": FieldDef(unit="[-1,1]", description="Normalized FinBERT score.", source="finbert"),
            "items[].impact": FieldDef(description="Heuristic impact bucket: low/medium/high.", source="scorer"),
            "items[].dedupe_cluster_size": FieldDef(unit="count", description="How many near-duplicates collapsed into this row.", source="simhash"),
            "items[].link": FieldDef(unit="url", description="Original article URL.", source="feed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "new_high_impact_for_tickers",
                "central_bank_press_release",
                "regulatory_action_for_tickers",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="top_returns_items_within_freshness_window",
                description="Every item's published_utc is within the configured freshness window.",
                inputs={"freshness": "6h"},
                assertions=["all_items_within_freshness_window"],
            ),
            SemanticTest(
                name="top_dedupe_collapses_duplicates",
                description="Two near-identical headlines from different sources collapse into one row with dedupe_cluster_size=2.",
                inputs={"dedupe": True},
                assertions=["dedupe_cluster_size_equals_2"],
            ),
            SemanticTest(
                name="top_no_silent_ticker_guess",
                description="An ambiguous headline (e.g. apple as a metaphor) yields tickers=[] rather than a guess.",
                inputs={},
                assertions=["tickers_empty_on_ambiguous_headline"],
            ),
            SemanticTest(
                name="top_sentiment_uses_finbert_not_placeholder",
                description="Sentiment scores across known bull/bear test headlines align with FinBERT reference.",
                inputs={"sentiment_overlay": True},
                assertions=["sentiment_score_matches_finbert_reference"],
            ),
            SemanticTest(
                name="top_filter_impact_high_excludes_low",
                description="With min_impact=high every returned item has impact == high.",
                inputs={"min_impact": "high"},
                assertions=["all_items_impact_equals_high"],
            ),
            SemanticTest(
                name="top_no_stale_or_synthetic_rows_when_providers_down",
                description="When both GDELT and RSS fail, items=[] and data_mode=provider_unavailable with a warning explaining both failed.",
                inputs={},
                assertions=[
                    "items_is_empty_array_when_all_providers_down",
                    "data_mode_equals_provider_unavailable",
                    "warning_lists_both_providers",
                ],
            ),
        ],
    )


__all__ = ["top"]
