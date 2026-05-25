"""SOSC — Social Sentiment Composite.

Composite social-sentiment surface that combines XSEN (X / Twitter
RoBERTa) and FinBERT-classified Reddit / StockTwits feeds into a single
per-symbol score. Every payload lists the contributing sources so the
analyst can see exactly which signals fed the composite.
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
def sosc() -> FunctionManifest:
    return FunctionManifest(
        code="SOSC",
        name="Social Sentiment Composite",
        category=Category.NEWS_INTEL,
        intent=(
            "Composite social-sentiment surface combining XSEN (X / Twitter RoBERTa) and "
            "FinBERT-classified Reddit / StockTwits feeds into a single per-symbol score. "
            "Every payload lists the contributing sources so the analyst can see exactly "
            "which signals fed the composite — no opaque black box."
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
                description="Ticker to score. Resolves to (cashtag, name) for the social adapters.",
            ),
            InputSpec(
                name="sources",
                label="Source set",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Which social adapters to include in the composite. Empty = all configured.",
                options=["xsen", "stocktwits", "reddit", "finbert_news"],
            ),
            InputSpec(
                name="window",
                label="Window",
                control=ControlKind.SELECT,
                required=False,
                description="Lookback window for source rows.",
                options=["1h", "6h", "24h", "7d"],
            ),
            InputSpec(
                name="min_messages",
                label="Min messages per source",
                control=ControlKind.NUMBER,
                required=False,
                description="Skip sources whose row count falls below this floor (avoids 1-message false signals).",
                min=1,
                max=200,
                step=5,
            ),
            InputSpec(
                name="provider_mode",
                label="Data mode",
                control=ControlKind.PROVIDER_MODE,
                required=False,
                description="Preferred data mode; the chain may downgrade and report it.",
                options=[
                    DataMode.LIVE_OFFICIAL.value,
                    DataMode.MODELED.value,
                    DataMode.CACHED_SNAPSHOT.value,
                ],
            ),
        ],
        defaults={
            "symbol": "AAPL",
            "sources": [],
            "window": "24h",
            "min_messages": 5,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=120, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["symbol", "composite_score", "composite_sources", "data_mode"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="source", label="Source", kind="tag"),
                ColumnSpec(key="messages_count", label="Msgs", kind="number", format="%d"),
                ColumnSpec(key="bullish_pct", label="Bull%", kind="percent", format="%.1f"),
                ColumnSpec(key="bearish_pct", label="Bear%", kind="percent", format="%.1f"),
                ColumnSpec(key="net_score", label="Net", kind="number", format="%.2f"),
                ColumnSpec(key="weight", label="Weight", kind="number", format="%.2f"),
                ColumnSpec(key="as_of", label="As of", kind="datetime", format="rel-time"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbol", label="Symbol", kind="badge"),
                CardSlot(key="composite_score", label="Composite", kind="big_number"),
                CardSlot(key="composite_label", label="Bias", kind="badge"),
                CardSlot(key="sources_count", label="Sources", kind="kpi"),
                CardSlot(key="messages_total", label="Messages", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "SOSC composes a per-symbol sentiment score from up to four social adapters. (1) "
            "XSEN runs the bundled RoBERTa over the auth-free X/Twitter Brave→syndication scrape "
            "and returns a (bullish_pct, bearish_pct, messages_count) triple. (2) StockTwits is "
            "queried via the cashtag stream and the bullish/bearish counts are read straight "
            "from the platform's own labels. (3) Reddit pulls the symbol's subreddit + cashtag "
            "and FinBERT scores each post body. (4) FinBERT_news is the FinBERT pass over the "
            "CN feed for the same window. Each source's net_score is (bullish_pct - bearish_pct)"
            " / 100 in [-1, +1]. Sources below min_messages are dropped (with a warning naming "
            "the dropped source). The composite is a message-weighted mean of the surviving "
            "per-source scores: composite = sum(net_score_i * messages_i) / sum(messages_i). "
            "The contributing source list (composite_sources) is ALWAYS surfaced in the payload "
            "so a downstream caller can see exactly which adapters contributed. When zero "
            "sources clear min_messages, composite_score is null, composite_sources=[], and a "
            "warning explains the empty composite — never a fabricated score."
        ),
        formula_dict={
            "source_net_score": Formula(
                expression=r"net_{i} = \frac{bullish\_pct_{i} - bearish\_pct_{i}}{100}",
                variables={
                    "bullish_pct_i": "Bullish share for source i (0..100)",
                    "bearish_pct_i": "Bearish share for source i (0..100)",
                },
                notes="Per-source net score in [-1, +1].",
            ),
            "composite_score": Formula(
                expression=r"composite = \frac{\sum_{i} net_{i} \cdot msgs_{i}}{\sum_{i} msgs_{i}}",
                variables={
                    "net_i": "Per-source net score",
                    "msgs_i": "Messages count for source i (post min_messages floor)",
                },
                notes="Message-weighted mean across surviving sources.",
            ),
        },
        field_dict={
            "symbol": FieldDef(description="Echoed input symbol (uppercased).", source="input"),
            "composite_score": FieldDef(unit="[-1,+1]", description="Message-weighted mean of surviving per-source net scores. Null when no source clears min_messages.", source="computed"),
            "composite_label": FieldDef(description="bullish / bearish / neutral derived from composite_score.", source="derived"),
            "composite_sources": FieldDef(description="List of source ids that contributed to the composite — surfaced for transparency.", source="derived"),
            "rows[].source": FieldDef(description="Source id (xsen / stocktwits / reddit / finbert_news).", source="adapter"),
            "rows[].messages_count": FieldDef(unit="count", description="Number of messages from the source in the window.", source="adapter"),
            "rows[].bullish_pct": FieldDef(unit="%", description="Bullish share of messages.", source="adapter"),
            "rows[].bearish_pct": FieldDef(unit="%", description="Bearish share of messages.", source="adapter"),
            "rows[].net_score": FieldDef(unit="[-1,+1]", description="Per-source net score.", source="computed"),
            "rows[].weight": FieldDef(description="Share of total messages this source contributed to the composite.", source="computed"),
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
                description="Asserts composite_sources is a non-empty array of source ids whenever composite_score is non-null — the composite never hides its inputs.",
                inputs={"symbol": "AAPL"},
                assertions=[
                    "composite_sources_is_array",
                    "composite_sources_non_empty_when_score_non_null",
                ],
            ),
            SemanticTest(
                name="sosc_below_min_messages_source_is_dropped",
                description="With min_messages=50 and a source returning 5 messages, asserts that source is excluded from composite_sources AND a warning names the dropped source.",
                inputs={"symbol": "AAPL", "min_messages": 50, "_mock": "low_message_source"},
                assertions=[
                    "low_message_source_not_in_composite_sources",
                    "warning_names_dropped_source",
                ],
            ),
            SemanticTest(
                name="sosc_no_sources_returns_null_score_not_fake",
                description="When zero sources clear min_messages, asserts composite_score is null and composite_sources=[].",
                inputs={"symbol": "ZZZZ", "_mock": "all_sources_empty"},
                assertions=[
                    "composite_score_is_null",
                    "composite_sources_empty_array",
                ],
            ),
            SemanticTest(
                name="sosc_composite_matches_weighted_mean",
                description="Asserts composite_score equals the message-weighted mean of per-source net_scores within 1e-6.",
                inputs={},
                assertions=["composite_score_matches_formula_within_1e-6"],
            ),
        ],
    )


__all__ = ["sosc"]
