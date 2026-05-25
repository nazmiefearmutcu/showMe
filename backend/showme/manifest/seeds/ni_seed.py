"""NI — News Impact Scorer (topic-scoped).

Topic-scoped news feed with per-item impact tag (low / medium / high).
The impact tag is a curated tag bucket, not a synthetic float — it
combines source authority, topic weight, sentiment magnitude, and
freshness decay through a documented heuristic.
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
def ni() -> FunctionManifest:
    return FunctionManifest(
        code="NI",
        name="News Impact",
        category=Category.NEWS_INTEL,
        intent=(
            "Topic-scoped news feed with a per-item impact TAG (low / medium / high) — never a "
            "synthetic float. Combines source authority, topic weight, sentiment magnitude, and "
            "freshness decay through a documented heuristic so analysts can trust the tag's "
            "provenance."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.CRYPTO,
            AssetClass.ETF,
            AssetClass.FX,
            AssetClass.COMMODITY,
            AssetClass.BOND,
            AssetClass.RATE,
            AssetClass.INDEX,
        ],
        inputs=[
            InputSpec(
                name="topic",
                label="Topic",
                control=ControlKind.SELECT,
                required=True,
                description="Topic preset; resolved to a curated query (MACRO=GDP OR CPI OR inflation; FED=Federal Reserve OR FOMC OR Powell; etc.).",
                options=["MACRO", "FED", "BANKS", "EARN", "CHIPS", "OIL", "TECH", "CRYPTO", "M&A", "IPO", "WAR"],
            ),
            InputSpec(
                name="query",
                label="Free-text query",
                control=ControlKind.TEXT,
                required=False,
                description="Override the topic with a free-text query.",
            ),
            InputSpec(
                name="limit",
                label="Headline cap",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum headlines to return.",
                min=1,
                max=200,
                step=10,
            ),
            InputSpec(
                name="threshold",
                label="Importance threshold",
                control=ControlKind.NUMBER,
                required=False,
                description="Importance score floor for critical-article flagging (0..100).",
                min=0,
                max=100,
                step=5,
            ),
            InputSpec(
                name="deep",
                label="Deep search",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Also pull from GDELT in addition to the primary RSS sources.",
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; the chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "topic": "MACRO",
            "query": "",
            "limit": 50,
            "threshold": 70,
            "deep": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="gdelt",
            fallbacks=["rss", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["topic", "items", "data_mode"],
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
                ColumnSpec(key="impact", label="Impact", kind="tag"),
                ColumnSpec(key="importance_score", label="Score", kind="number", format="%.0f"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="link", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_items", label="Items", kind="kpi"),
                CardSlot(key="high_impact_count", label="High Impact", kind="kpi"),
                CardSlot(key="medium_impact_count", label="Medium", kind="kpi"),
                CardSlot(key="low_impact_count", label="Low", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "NI resolves the topic to a curated query (or accepts a free-text query) and pulls "
            "matching headlines from GDELT (primary) and RSS (fallback). Each item is enriched "
            "via news_intelligence.enrich_articles which computes a 0..100 importance_score and "
            "a FinBERT sentiment label. The per-item `impact` field is then derived as a tag "
            "bucket — NOT a synthetic float — by mapping the importance_score and sentiment "
            "magnitude through the heuristic in `formula_dict.impact_tag`. The tag value is one "
            "of {low, medium, high}. Critical_articles flags rows above the threshold for the "
            "alert lane. When both adapters miss, items=[] with a warning explaining both "
            "providers failed — no synthetic headlines are ever surfaced."
        ),
        formula_dict={
            "impact_tag": Formula(
                expression=(
                    r"impact = \begin{cases} \text{high} & importance\_score \ge 70 "
                    r"\text{ or } |sentiment\_score| \ge 0.8 \\ "
                    r"\text{medium} & importance\_score \ge 40 \\ "
                    r"\text{low} & \text{otherwise} \end{cases}"
                ),
                variables={
                    "importance_score": "0..100 from news_intelligence.enrich_articles",
                    "sentiment_score": "-1..+1 normalized FinBERT score",
                },
                notes="Tag bucket, not a numeric score. The thresholds are committed in repo so the analyst can sanity-check.",
            ),
        },
        field_dict={
            "topic": FieldDef(description="Resolved topic preset or echoed free-text query.", source="input"),
            "items[].published_utc": FieldDef(unit="iso8601", description="Article publish time.", source="feed"),
            "items[].source": FieldDef(description="Publisher domain.", source="derived"),
            "items[].title": FieldDef(description="Headline text.", source="feed"),
            "items[].impact": FieldDef(description="Tag bucket (low/medium/high) — never a float.", source="computed"),
            "items[].importance_score": FieldDef(unit="[0,100]", description="Importance score from news_intelligence.", source="computed"),
            "items[].sentiment": FieldDef(description="pos/neu/neg from FinBERT.", source="finbert"),
            "items[].link": FieldDef(unit="url", description="Direct link to the source article.", source="feed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["high_impact_for_topic", "critical_article_above_threshold"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="ni_impact_is_a_tag_not_float",
                description="Asserts every item's impact field is one of the canonical strings 'low' / 'medium' / 'high' — never a float, int, or null.",
                inputs={"topic": "MACRO"},
                assertions=[
                    "every_item_impact_in_low_medium_high",
                    "no_item_impact_is_numeric",
                ],
            ),
            SemanticTest(
                name="ni_high_impact_matches_heuristic",
                description="For each item tagged high, asserts importance_score >= 70 OR |sentiment_score| >= 0.8 (matches the documented heuristic).",
                inputs={"topic": "FED"},
                assertions=["every_high_item_matches_heuristic"],
            ),
            SemanticTest(
                name="ni_provider_outage_returns_empty_not_synthetic",
                description="When both GDELT and RSS fail, asserts items=[] and warning lists the failed adapters; no synthetic headlines appear.",
                inputs={"_mock": "all_news_down"},
                assertions=[
                    "items_empty_array",
                    "warning_lists_both_providers",
                ],
            ),
            SemanticTest(
                name="ni_critical_count_matches_threshold",
                description="critical-count card equals the number of items with importance_score >= threshold.",
                inputs={"topic": "MACRO", "threshold": 80},
                assertions=["critical_count_matches_threshold_filter"],
            ),
        ],
    )


__all__ = ["ni"]
