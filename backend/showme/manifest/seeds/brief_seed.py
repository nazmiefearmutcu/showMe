"""BRIEF — Daily Research Briefing.

Composes a portfolio-aware daily research briefing from existing
ShowMe surfaces: PORT (positions), WATCH (watchlist), TOP (top news),
CN (per-symbol news), and ECO (calendar). The brief is markdown +
structured payload. Every claim cites the evidence row it came from —
no synthetic summaries, no fabricated quotes.
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
def brief() -> FunctionManifest:
    return FunctionManifest(
        code="BRIEF",
        name="Daily Research Briefing",
        category=Category.NEWS_INTEL,
        intent=(
            "A portfolio-aware daily research briefing composed from PORT positions, "
            "WATCH symbols, TOP news, CN per-symbol news, and ECO calendar — emitted as "
            "markdown + structured payload where every claim cites the evidence row it "
            "came from. No synthetic summaries, no fabricated quotes."
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
                name="watchlist",
                label="Watchlist",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Symbols to include in the brief. Empty = read from PORT + WATCH.",
            ),
            InputSpec(
                name="sections",
                label="Sections",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Which article sections to render: top_stories (cross-asset headlines) and watchlist (per-symbol headlines). Other values are reported in warnings and skipped.",
                options=["top_stories", "watchlist"],
            ),
            InputSpec(
                name="limit",
                label="Stories per section",
                control=ControlKind.NUMBER,
                required=False,
                description="Max stories surfaced per section (1..50).",
                min=1,
                max=50,
                step=5,
            ),
            InputSpec(
                name="live",
                label="Live composition",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true, recompose from live PORT/WATCH/TOP/CN; otherwise return the last cached brief.",
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
            "watchlist": [],
            "sections": ["top_stories", "watchlist"],
            "limit": 25,
            "live": True,
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
        caching=CachingPolicy(ttl_seconds=900, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["status", "markdown", "articles", "watchlist", "article_count"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="published_at", label="Time", kind="datetime", format="rel-time"),
                ColumnSpec(key="matched_symbol", label="Symbol", kind="tag"),
                ColumnSpec(key="source", label="Source", kind="tag"),
                ColumnSpec(key="title", label="Title", kind="text"),
                ColumnSpec(key="url", label="Evidence", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="article_count", label="Stories", kind="kpi"),
                CardSlot(key="watchlist_size", label="Watchlist", kind="kpi"),
                CardSlot(key="positions_covered", label="Positions", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "BRIEF composes the briefing from the Awareness news service — it does NOT call an LLM "
            "and does NOT fabricate prose. (1) With no watchlist input, read the symbols of the "
            "user's portfolio positions (engine.portfolio.state) and of the saved watchlists "
            "(watchlist store), and merge them; an explicit watchlist input replaces that default. "
            "With the watchlist section requested and no symbols at all, the status is 'needs_input' "
            "and no news is fetched. (2) The top_stories section is one TOP() call (cross-asset "
            "Awareness top stories, standard quality or better); the watchlist section is one CN() "
            "call per symbol (the first 12). READ() and ECO() are not called. The sections input "
            "selects which sections are composed (default both); other requested sections are "
            "reported in warnings, and a request with no recognised section is 'input_error'. The "
            "limit applies per section. The markdown lists each section under its own heading; every "
            "bullet links to its article and names the publisher, tier, quality verdict and the "
            "sentiment label Awareness assigned (BRIEF never re-scores sentiment). The structured "
            "`articles` array carries the same rows so downstream callers can re-render without "
            "re-parsing markdown. If every call fails, status is 'provider_unavailable' with "
            "Awareness's reason; if some fail, the brief stays live with partial=true and names the "
            "missing legs; 'empty' means Awareness answered and no headline matched — the brief "
            "never invents a 'no news today, all quiet' summary."
        ),
        field_dict={
            "status": FieldDef(description="ok / empty / provider_unavailable / needs_input / input_error.", source="derived"),
            "markdown": FieldDef(description="Markdown rendering of the brief — every bullet links to its evidence row.", source="composed"),
            "articles": FieldDef(description="Structured rows of the headlines cited in the markdown body.", source="read"),
            "watchlist": FieldDef(description="Effective watchlist used (input + positions).", source="composed"),
            "article_count": FieldDef(unit="count", description="Number of cited articles.", source="derived"),
            "articles[].url": FieldDef(unit="url", description="Direct HTTPS link to the source article — the evidence cite (same value as articles[].link).", source="read"),
            "articles[].title": FieldDef(description="Headline text quoted from the source.", source="read"),
            "articles[].source": FieldDef(description="Publisher name (for RSS items, the feed title).", source="read"),
            "articles[].matched_symbol": FieldDef(description="Symbol this article was tagged to.", source="read"),
            "next_actions": FieldDef(description="Suggested follow-up actions (e.g. 'no live headlines — broaden watchlist').", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="brief_evidence_links_present",
                description="Asserts every bullet in markdown has an http(s) link AND every articles[] row has a non-empty url. The brief must cite, never summarize without evidence.",
                inputs={"watchlist": ["AAPL", "MSFT"]},
                assertions=[
                    "every_markdown_bullet_has_link",
                    "every_article_has_evidence_url",
                ],
            ),
            SemanticTest(
                name="brief_no_synthetic_summary_when_no_news",
                description="When TOP and the symbol headline calls return zero articles, asserts status='provider_unavailable', markdown lists 'No live watchlist headlines were returned' (no invented quotes), and next_actions explains the empty result. READ is not called by BRIEF.",
                inputs={"_mock": "news_empty"},
                assertions=[
                    "status_equals_provider_unavailable_when_empty",
                    "markdown_has_no_synthetic_quotes",
                    "next_actions_explains_empty",
                ],
            ),
            SemanticTest(
                name="brief_watchlist_includes_portfolio_positions",
                description="Asserts effective watchlist is the union of input watchlist and PORT positions.",
                inputs={"watchlist": ["AAPL"]},
                assertions=["watchlist_includes_port_positions"],
            ),
            SemanticTest(
                name="brief_article_count_matches_articles_length",
                description="Asserts article_count == len(articles); the count cannot drift from the array.",
                inputs={},
                assertions=["article_count_matches_articles_length"],
            ),
        ],
    )


__all__ = ["brief"]
