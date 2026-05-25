"""NSE — News Search Engine.

Full-text search across the unified news index — GDELT primary, RSS
fallback. Supports phrase queries, boolean operators, source whitelist,
ticker / topic / date-range filters; returns paginated hits with
highlighted matches and direct article links.
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
def nse() -> FunctionManifest:
    return FunctionManifest(
        code="NSE",
        name="News Search Engine",
        category=Category.NEWS_INTEL,
        intent=(
            "Full-text search across the unified news index — GDELT primary, RSS fallback. "
            "Supports phrase queries, boolean operators, source whitelist, ticker / topic / "
            "date-range filters; returns paginated hits with highlighted matches and direct "
            "article links to the source publisher."
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
                name="query",
                label="Query",
                control=ControlKind.TEXT,
                required=True,
                description="Full-text query. Supports phrases (\"foo bar\"), boolean operators (AND / OR / NOT), and field-scoped terms (title:foo, source:reuters.com).",
            ),
            InputSpec(
                name="sources",
                label="Source whitelist",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to these publisher domains.",
            ),
            InputSpec(
                name="tickers",
                label="Tickers",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to items tagged with these tickers.",
            ),
            InputSpec(
                name="topics",
                label="Topics",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to editorial topic tags.",
                options=[
                    "earnings",
                    "m&a",
                    "central_bank",
                    "geopolitics",
                    "regulatory",
                    "macro",
                    "crypto_protocol",
                ],
            ),
            InputSpec(
                name="date_range",
                label="Date range",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Restrict by article published_utc.",
            ),
            InputSpec(
                name="limit",
                label="Page size",
                control=ControlKind.NUMBER,
                required=False,
                description="Hits per page (1..200).",
                min=1,
                max=200,
                step=10,
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
            "query": "",
            "sources": [],
            "tickers": [],
            "topics": [],
            "date_range": "last_30d",
            "limit": 50,
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
            must_have=["as_of", "query", "hits", "total_estimate", "data_mode"],
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
                ColumnSpec(key="title_highlighted", label="Title", kind="text"),
                ColumnSpec(key="snippet_highlighted", label="Snippet", kind="text"),
                ColumnSpec(key="tickers", label="Tickers", kind="tag"),
                ColumnSpec(key="topic", label="Topic", kind="tag"),
                ColumnSpec(key="link", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_estimate", label="Total Hits", kind="kpi"),
                CardSlot(key="returned_count", label="Returned", kind="kpi"),
                CardSlot(key="sources_active", label="Sources", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "NSE parses the query string into the GDELT DOC query DSL — phrases stay quoted, "
            "boolean operators (AND/OR/NOT) and field-scoped terms (title:, source:) are "
            "translated to GDELT's syntax, free terms become an implicit AND. The request also "
            "passes the date_range and source whitelist through GDELT's startdatetime / "
            "enddatetime / domain filters so the index does the filtering instead of "
            "post-filtering in Python. RSS is consulted as a fallback when GDELT rate-limits or "
            "is unavailable; the RSS path runs a substring scan over the curated feed cache "
            "with the same filters. Highlights are server-side regex matches wrapped with "
            "<mark> tags. `total_estimate` is GDELT's reported count (RSS reports the post-"
            "filter hit count). When both providers fail, hits=[] with a warning listing both "
            "adapters — no synthetic results are ever returned."
        ),
        field_dict={
            "query": FieldDef(description="Echoed input query string.", source="input"),
            "hits[].published_utc": FieldDef(unit="iso8601", description="Article publish time.", source="feed"),
            "hits[].source": FieldDef(description="Publisher domain.", source="derived"),
            "hits[].title_highlighted": FieldDef(description="Title with <mark>...</mark> around matched terms.", source="computed"),
            "hits[].snippet_highlighted": FieldDef(description="Snippet excerpt with <mark>...</mark> around matched terms.", source="computed"),
            "hits[].tickers": FieldDef(description="Detected tickers; empty when uncertain.", source="ner"),
            "hits[].topic": FieldDef(description="Editorial topic tag.", source="classifier"),
            "hits[].link": FieldDef(unit="url", description="Direct link to the source article.", source="feed"),
            "total_estimate": FieldDef(unit="count", description="Estimated total hits (GDELT count or RSS post-filter count).", source="adapter"),
            "returned_count": FieldDef(unit="count", description="Number of hits in this page.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="nse_query_required_and_echoed",
                description="Asserts an empty query returns a 400-equivalent warning AND when query is set it is echoed in the response.",
                inputs={"query": "Federal Reserve"},
                assertions=["query_echoed_in_response"],
            ),
            SemanticTest(
                name="nse_highlights_match_terms",
                description="For query='earnings', asserts every hit's title_highlighted or snippet_highlighted contains <mark>earnings</mark> (case-insensitive).",
                inputs={"query": "earnings"},
                assertions=["every_hit_has_mark_around_match"],
            ),
            SemanticTest(
                name="nse_source_whitelist_restricts_hits",
                description="With sources=['reuters.com'], asserts every hit.source ends with 'reuters.com'.",
                inputs={"query": "fed", "sources": ["reuters.com"]},
                assertions=["every_hit_source_in_whitelist"],
            ),
            SemanticTest(
                name="nse_no_synthetic_hits_on_provider_outage",
                description="When both GDELT and RSS fail, asserts hits=[] and warning lists both adapters.",
                inputs={"query": "x", "_mock": "all_news_down"},
                assertions=[
                    "hits_empty_array",
                    "warning_lists_both_providers",
                ],
            ),
        ],
    )


__all__ = ["nse"]
