"""CN — Company News.

Symbol-scoped news for equities and crypto. Backend handler
``engine/functions/news/cn.py`` runs an asset-class-aware source order
(RSS primary, finnhub_news / yfinance / GDELT optional) with
symbol-term enrichment and a critical-article alert pass.
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
def cn() -> FunctionManifest:
    return FunctionManifest(
        code="CN",
        name="Company News",
        category=Category.NEWS_INTEL,
        intent=(
            "Show symbol-scoped headlines with enrichment, importance scoring, and a critical-article "
            "alert lane — drilldown surface for any pane that picks a symbol."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.CRYPTO,
            AssetClass.ETF,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Equity ticker or crypto base; resolves to the company/coin entity for ticker-aware enrichment.",
            ),
            InputSpec(
                name="limit",
                label="Headline cap",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum headlines to return; defaults to 50.",
                min=1,
                max=200,
                step=10,
            ),
            InputSpec(
                name="threshold",
                label="Importance threshold",
                control=ControlKind.NUMBER,
                required=False,
                description="Importance score floor for surfacing items (0-100).",
                min=0,
                max=100,
                step=5,
            ),
            InputSpec(
                name="deep",
                label="Deep search",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Also pull from yfinance + GDELT in addition to the primary RSS sources.",
            ),
            InputSpec(
                name="include_yfinance",
                label="Include yfinance",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Add yfinance to the source order.",
            ),
            InputSpec(
                name="include_gdelt",
                label="Include GDELT",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Add GDELT to the source order.",
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
            "limit": 50,
            "threshold": 70,
            "deep": False,
            "include_yfinance": False,
            "include_gdelt": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        # Real handler defaults to ``["rss"]`` and conditionally appends
        # finnhub_news (when API key present), yfinance (when deep), and
        # gdelt (when deep). RSS is the canonical primary across both
        # equity and crypto asset classes.
        provider_chain=ProviderChain(
            primary="rss",
            fallbacks=["gdelt", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.DELAYED_REFERENCE,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=False),
        # CN returns a list of enriched article rows directly; the engine
        # wraps it in a FunctionResult.data list-or-dict. Pin the array
        # shape so downstream callers can rely on ``items`` semantics
        # without coercing.
        output_contract=OutputContract(
            must_have=["symbol", "rows"],
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
                ColumnSpec(key="importance_score", label="Importance", kind="number", format="%.0f"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="link", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_items", label="Headlines", kind="kpi"),
                CardSlot(key="critical_count", label="Critical", kind="kpi"),
                CardSlot(key="top_importance_score", label="Top score", kind="kpi"),
                CardSlot(key="sources_active", label="Sources", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "CN runs an asset-class-aware source order. For equities the default chain is RSS only; "
            "finnhub_news is appended when an API key is configured, yfinance and GDELT are appended "
            "when deep=True. Each adapter receives symbol-derived terms so the RSS fetcher can scope "
            "feeds to the company. Returned articles are deduped (URL + title hash) and enriched via "
            "engine.services.news_intelligence.enrich_articles which assigns an importance_score and "
            "FinBERT sentiment label; critical_articles flags the rows above the configured threshold "
            "for the alert lane. CRYPTO routes through a parallel path with crypto-specific term lists "
            "(coin name, ticker, common context terms) and an optional cryptocompare adapter when "
            "keyed. When every adapter misses, CN returns provider-unavailable placeholder rows that "
            "explain why and never fabricate headlines."
        ),
        field_dict={
            "symbol": FieldDef(description="Canonical equity ticker or crypto base.", source="instrument"),
            "rows[].published_utc": FieldDef(unit="iso8601", description="Article publish time.", source="feed"),
            "rows[].source": FieldDef(description="Feed name (rss / yfinance / finnhub_news / gdelt).", source="adapter"),
            "rows[].title": FieldDef(description="Headline text.", source="feed"),
            "rows[].link": FieldDef(unit="url", description="Original article URL.", source="feed"),
            "rows[].importance_score": FieldDef(unit="[0,100]", description="Enrichment score from news_intelligence.", source="computed"),
            "rows[].sentiment": FieldDef(description="pos/neu/neg from FinBERT.", source="finbert"),
            "rows[].is_critical": FieldDef(description="True when importance_score >= threshold.", source="computed"),
            "critical_count": FieldDef(unit="count", description="Number of rows above threshold.", source="computed"),
            "top_importance_score": FieldDef(unit="[0,100]", description="Highest importance_score in the returned set.", source="computed"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=AlertingSpec(
            conditions=["critical_article_for_symbol", "new_headline_above_threshold"],
            delivery=["tray", "notification", "log"],
        ),
        semantic_tests=[
            SemanticTest(
                name="cn_aapl_returns_real_headlines",
                description="CN for AAPL returns rows with title + link + a non-empty source name.",
                inputs={"symbol": "AAPL", "limit": 25},
                assertions=[
                    "rows_non_empty",
                    "every_row_has_title",
                    "every_row_has_link",
                    "every_row_source_non_empty",
                ],
            ),
            SemanticTest(
                name="cn_btc_routes_to_crypto_path",
                description="CN for BTC takes the crypto code path (RSS with crypto term list, optional cryptocompare).",
                inputs={"symbol": "BTC", "limit": 25},
                assertions=[
                    "rows_non_empty",
                    "asset_class_equals_crypto",
                    "no_synthetic_placeholder_when_provider_ok",
                ],
            ),
            SemanticTest(
                name="cn_provider_outage_returns_placeholder_not_fake_news",
                description="When every news adapter fails, CN returns provider-unavailable rows explaining the outage, not invented headlines.",
                inputs={"symbol": "ZZZZZZ"},
                assertions=[
                    "rows_explain_provider_outage",
                    "no_row_with_invented_title",
                ],
            ),
            SemanticTest(
                name="cn_threshold_filters_critical_count",
                description="critical_count equals the number of rows with importance_score >= threshold.",
                inputs={"symbol": "AAPL", "threshold": 80},
                assertions=["critical_count_matches_threshold_filter"],
            ),
        ],
    )


__all__ = ["cn"]
