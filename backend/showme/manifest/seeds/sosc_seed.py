"""SOSC — Entity Sentiment.

Per-symbol sentiment read entirely from Awareness: FinBERT scores of Awareness-collected
news (series, headlines), the ApeWisdom social-buzz rank when the ticker is listed, and
the GDELT DOC tone series Awareness stored for the entity.
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
def sosc() -> FunctionManifest:
    return FunctionManifest(
        code="SOSC",
        name="Social Sentiment",
        category=Category.NEWS_INTEL,
        intent=(
            "Per-symbol news sentiment from Awareness: FinBERT item scores over a 1d, 7d or 30d "
            "window with the headlines behind them, the ApeWisdom social-buzz rank when listed, "
            "and the GDELT tone series for the entity. Every figure is sourced; nothing is modelled."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.CRYPTO,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Ticker to score. Crypto quote suffixes (BTCUSDT, BTC-USD) are stripped to the base token.",
            ),
            InputSpec(
                name="window",
                label="Window",
                control=ControlKind.SELECT,
                required=False,
                description="Lookback window: 1d or 7d (hourly buckets) or 30d (daily buckets).",
                options=["1d", "7d", "30d"],
            ),
        ],
        defaults={
            "symbol": "AAPL",
            "window": "7d",
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
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["symbol", "news", "headlines", "gdelt_tone", "methodology"],
            rows=True,
            series=True,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="platform", label="Source", kind="tag"),
                ColumnSpec(key="mentions", label="Mentions", kind="number", format="%d"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="number", format="%.2f"),
                ColumnSpec(key="rank", label="Rank", kind="number", format="%d"),
                ColumnSpec(key="trend", label="Trend", kind="tag"),
            ],
            sortable=True,
            filterable=False,
        ),
        methodology=(
            "SOSC reports Awareness entity sentiment for the symbol over the chosen window. Each "
            "Awareness-collected news item carries a FinBERT label and score in [-1, +1]; news.mean "
            "is the arithmetic mean of those scores, news.weighted_mean weights each item by its "
            "FinBERT confidence times its source-quality score (computed by Awareness), and the "
            "positive and negative shares are label fractions. The series is bucketed hourly for "
            "1d and 7d windows and daily for 30d. headlines are the newest items behind the score. "
            "social is the ApeWisdom rank and mention change for the ticker when it appears on the "
            "ranked list, otherwise null. gdelt_tone is the GDELT DOC tone series stored by "
            "Awareness, shown in GDELT's native scale without rescaling. When Awareness is down the "
            "function returns provider_unavailable; when the window has no items it returns empty. "
            "No sentiment value is ever estimated or defaulted."
        ),
        formula_dict={
            "news_mean": Formula(
                expression=r"\bar{s} = \frac{1}{n}\sum_{i=1}^{n} s_i",
                variables={
                    "s_i": "FinBERT item score in [-1, +1] for news item i",
                    "n": "Number of news items in the window (news.count)",
                },
                notes="Unweighted mean as reported by Awareness; weighted_mean uses confidence x quality.",
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Base symbol scored (uppercased, quote suffix removed).", source="input"),
            "news.mean": FieldDef(unit="[-1,+1]", description="Mean FinBERT item score for the window.", source="awareness"),
            "news.weighted_mean": FieldDef(unit="[-1,+1]", description="Confidence and quality weighted mean.", source="awareness"),
            "news.series": FieldDef(description="Bucketed count, mean and label counts.", source="awareness"),
            "headlines": FieldDef(description="Newest news items behind the score, with item label and score.", source="awareness"),
            "social": FieldDef(description="ApeWisdom rank and mention change for the ticker, or null.", source="awareness"),
            "gdelt_tone": FieldDef(description="GDELT DOC tone series for the entity (native scale).", source="awareness"),
            "rows[].mentions": FieldDef(unit="count", description="News item count or ApeWisdom mentions.", source="awareness"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="sosc_composite_sources_listed_in_payload",
                description=(
                    "Asserts the sources feeding the payload (awareness:sentiment and the "
                    "providers listed in metadata.providers) are named on every ok response."
                ),
                inputs={"symbol": "AAPL"},
                assertions=[
                    "sources_is_array",
                    "providers_listed_in_metadata",
                ],
            ),
            SemanticTest(
                name="sosc_no_news_returns_empty_not_score",
                description="When the window holds no items, asserts status is empty and news.mean is null.",
                inputs={"symbol": "ZZZZ"},
                assertions=["status_empty", "news_mean_is_null"],
            ),
            SemanticTest(
                name="sosc_awareness_down_is_provider_unavailable",
                description="When awareness cannot answer, asserts provider_unavailable with no rows and no score.",
                inputs={"symbol": "AAPL", "_mock": "awareness_down"},
                assertions=["status_provider_unavailable", "rows_empty", "news_is_absent"],
            ),
            SemanticTest(
                name="sosc_window_maps_to_bucket",
                description="Asserts 1d and 7d request hourly buckets and 30d requests daily buckets.",
                inputs={"symbol": "AAPL", "window": "30d"},
                assertions=["bucket_is_1d_for_30d"],
            ),
        ],
    )


__all__ = ["sosc"]
