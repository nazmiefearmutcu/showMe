"""NALRT — News Alerts Center.

User-defined news alerts: condition multiselect (keyword match, ticker
match, severity, sentiment threshold, source whitelist), per-rule
delivery (tray / notification / log), and a live alerts feed showing
recent fires with source attribution.
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
            "User-defined news alerts: condition multiselect (keyword, ticker, severity, "
            "sentiment threshold, source whitelist), per-rule delivery (tray / notification "
            "/ log), and a live alerts feed showing recent fires with source attribution and "
            "the matched rule's id."
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
                name="conditions",
                label="Conditions",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Which alert condition primitives to enable for this rule set.",
                options=[
                    "keyword_match",
                    "ticker_match",
                    "severity_threshold",
                    "sentiment_threshold",
                    "source_whitelist",
                    "topic_match",
                    "regulatory_action",
                    "central_bank_release",
                ],
            ),
            InputSpec(
                name="keywords",
                label="Keywords",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Keyword list for keyword_match (case-insensitive, substring).",
            ),
            InputSpec(
                name="tickers",
                label="Tickers",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Ticker list for ticker_match (matches CN/TOP tagging output).",
            ),
            InputSpec(
                name="severity_floor",
                label="Severity floor",
                control=ControlKind.SELECT,
                required=False,
                description="Drop alerts below this severity.",
                options=["low", "medium", "high", "critical"],
            ),
            InputSpec(
                name="sentiment_threshold",
                label="Sentiment threshold",
                control=ControlKind.NUMBER,
                required=False,
                description="|sentiment_score| >= threshold (0..1) to fire.",
                min=0.0,
                max=1.0,
                step=0.05,
            ),
            InputSpec(
                name="delivery",
                label="Delivery",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Delivery channels for matched alerts.",
                options=["tray", "notification", "log"],
            ),
            InputSpec(
                name="lookback",
                label="Feed lookback",
                control=ControlKind.SELECT,
                required=False,
                description="How far back to render the alerts feed.",
                options=["1h", "6h", "24h", "7d"],
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
            "conditions": ["keyword_match", "ticker_match", "severity_threshold"],
            "keywords": [],
            "tickers": [],
            "severity_floor": "medium",
            "sentiment_threshold": 0.5,
            "delivery": ["tray"],
            "lookback": "24h",
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "rules", "fires", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="fired_utc", label="Fired", kind="datetime", format="rel-time"),
                ColumnSpec(key="rule_id", label="Rule", kind="tag"),
                ColumnSpec(key="condition", label="Condition", kind="tag"),
                ColumnSpec(key="symbol", label="Symbol", kind="tag"),
                ColumnSpec(key="source", label="Source", kind="tag"),
                ColumnSpec(key="title", label="Headline", kind="text"),
                ColumnSpec(key="severity", label="Severity", kind="tag"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="link", label="Article", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="rules_active", label="Rules", kind="kpi"),
                CardSlot(key="fires_count", label="Fires", kind="kpi"),
                CardSlot(key="critical_count", label="Critical", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "NALRT scans the unified news stream (TOP + CN feeds + curated wire pulls) against "
            "every active rule on each tick. A rule is a conjunction of the enabled condition "
            "primitives — keyword_match (substring on title+body), ticker_match (exact match "
            "against CN/TOP's tagger), severity_threshold (>= floor), sentiment_threshold "
            "(|score| >= threshold), source_whitelist (publisher in list), and the curated "
            "primitives (regulatory_action, central_bank_release). When all conditions match, "
            "a fire row is recorded with the matched rule_id, condition list, and a verbatim "
            "snapshot of the source article (title + source + link + published_utc). Fires are "
            "delivered to the configured channels — tray (in-app drawer), notification (OS), "
            "log (persistent JSONL). The feed in the response carries every fire within the "
            "lookback window; matched rules carry no synthetic content — every row points back "
            "to a real article URL."
        ),
        field_dict={
            "rules[].id": FieldDef(description="Stable rule id (hash of the rule definition).", source="computed"),
            "rules[].conditions": FieldDef(description="Active condition primitives for this rule.", source="input"),
            "rules[].delivery": FieldDef(description="Delivery channels for this rule's fires.", source="input"),
            "fires[].fired_utc": FieldDef(unit="iso8601", description="When the alert fired.", source="scanner"),
            "fires[].rule_id": FieldDef(description="Matched rule id.", source="scanner"),
            "fires[].condition": FieldDef(description="Primary condition that triggered the fire.", source="scanner"),
            "fires[].symbol": FieldDef(description="Symbol tag from CN/TOP.", source="tagger"),
            "fires[].source": FieldDef(description="Publisher domain.", source="article"),
            "fires[].title": FieldDef(description="Verbatim source headline — no rephrasing.", source="article"),
            "fires[].severity": FieldDef(description="Severity from enrichment (low/medium/high/critical).", source="enrichment"),
            "fires[].sentiment": FieldDef(description="pos/neu/neg from FinBERT.", source="finbert"),
            "fires[].link": FieldDef(unit="url", description="Direct link to the source article.", source="article"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=[
                "keyword_match",
                "ticker_match",
                "severity_threshold",
                "sentiment_threshold",
                "source_whitelist",
                "topic_match",
                "regulatory_action",
                "central_bank_release",
            ],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="nalrt_fire_links_to_real_article",
                description="Asserts every fire row has a non-empty link AND title is verbatim from the source article (not rephrased).",
                inputs={"conditions": ["keyword_match"], "keywords": ["earnings"]},
                assertions=[
                    "every_fire_has_link",
                    "every_fire_title_matches_source_article_verbatim",
                ],
            ),
            SemanticTest(
                name="nalrt_severity_floor_excludes_below",
                description="With severity_floor='high', asserts every fire has severity ∈ {high, critical}.",
                inputs={"severity_floor": "high"},
                assertions=["every_fire_severity_ge_high"],
            ),
            SemanticTest(
                name="nalrt_rule_id_is_stable",
                description="Same rule definition produces the same rule_id across calls (id is a hash of the rule, not random).",
                inputs={},
                assertions=["rule_id_deterministic_for_same_definition"],
            ),
            SemanticTest(
                name="nalrt_no_synthetic_fires",
                description="When the unified news stream has no matches in the lookback, asserts fires=[] and no synthetic placeholder row appears.",
                inputs={"_mock": "stream_no_match"},
                assertions=["fires_empty_array_on_no_match"],
            ),
        ],
    )


__all__ = ["nalrt"]
