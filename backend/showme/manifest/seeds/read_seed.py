"""READ — Saved-articles Reading List.

Persistent reading list backed by the internal saved-articles store.
Users save articles from CN / NI / NSE / TOP; READ surfaces the
in-progress queue, the read/unread state per item, optional tag
filters, and a one-click open-back-in-source action.
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
def read() -> FunctionManifest:
    return FunctionManifest(
        code="READ",
        name="Reading List",
        category=Category.NEWS_INTEL,
        intent=(
            "Persistent reading list backed by the internal saved-articles store. Users save "
            "from CN / NI / NSE / TOP; READ surfaces the in-progress queue, read/unread state, "
            "tag filters, and one-click open-back-in-source so analysts can keep a working "
            "reading queue without bouncing between feeds."
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
                label="Symbols",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter the queue by symbol tag.",
            ),
            InputSpec(
                name="status",
                label="Status",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Read state filter.",
                options=["unread", "in_progress", "read", "archived"],
            ),
            InputSpec(
                name="tags",
                label="Tags",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict to items with these user tags.",
            ),
            InputSpec(
                name="limit",
                label="Limit",
                control=ControlKind.NUMBER,
                required=False,
                description="Max items to render (1..200).",
                min=1,
                max=200,
                step=10,
            ),
            InputSpec(
                name="live",
                label="Refresh from feeds",
                control=ControlKind.BOOLEAN,
                required=False,
                description="When true, refresh saved-article freshness by re-fetching source feeds; otherwise serve from store.",
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
            "status": ["unread", "in_progress"],
            "tags": [],
            "limit": 50,
            "live": False,
            "provider_mode": DataMode.CACHED_SNAPSHOT.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=60, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "articles", "article_count"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="saved_utc", label="Saved", kind="datetime", format="rel-time"),
                ColumnSpec(key="status", label="Status", kind="tag"),
                ColumnSpec(key="title", label="Title", kind="text"),
                ColumnSpec(key="matched_symbol", label="Symbol", kind="tag"),
                ColumnSpec(key="source", label="Source", kind="tag"),
                ColumnSpec(key="tags", label="Tags", kind="tag"),
                ColumnSpec(key="published_utc", label="Published", kind="datetime", format="rel-time"),
                ColumnSpec(key="link", label="Open", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="article_count", label="Articles", kind="kpi"),
                CardSlot(key="unread_count", label="Unread", kind="kpi"),
                CardSlot(key="in_progress_count", label="In Progress", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "READ is backed by the internal saved-articles store (engine/services/news_store). "
            "Articles get saved from CN / NI / NSE / TOP via a 'Save' action that writes a row "
            "with {url, title, source, published_utc, matched_symbol, tags, status}. READ reads "
            "the store, applies the input filters (watchlist, status, tags), and returns the "
            "rows in saved-time desc. When live=true, the dropped freshness path re-fetches the "
            "source URL's open-graph metadata to detect updated titles / removed articles and "
            "marks broken links with a warning. Status transitions (unread → in_progress → "
            "read → archived) are recorded server-side via separate /api/read/mark endpoints; "
            "READ surfaces the current status without mutation. When the store is missing or "
            "empty, articles=[] with a clear setup-hint warning — no synthetic placeholder rows."
        ),
        field_dict={
            "articles[].saved_utc": FieldDef(unit="iso8601", description="When the article was added to the queue.", source="store"),
            "articles[].status": FieldDef(description="unread / in_progress / read / archived.", source="store"),
            "articles[].title": FieldDef(description="Headline as captured at save time.", source="store"),
            "articles[].matched_symbol": FieldDef(description="Symbol tag carried in from the originating feed.", source="store"),
            "articles[].source": FieldDef(description="Publisher domain.", source="store"),
            "articles[].tags": FieldDef(description="User-supplied tags for the article.", source="store"),
            "articles[].published_utc": FieldDef(unit="iso8601", description="Original publish time.", source="store"),
            "articles[].link": FieldDef(unit="url", description="Direct link to the source article.", source="store"),
            "article_count": FieldDef(unit="count", description="Number of articles in the filtered view.", source="derived"),
            "unread_count": FieldDef(unit="count", description="Unread items in the unfiltered queue.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="read_returns_saved_rows_only",
                description="Asserts every row in articles comes from the saved-articles store — never a synthetic placeholder.",
                inputs={},
                assertions=["every_article_has_store_id"],
            ),
            SemanticTest(
                name="read_status_filter_applies",
                description="With status=['unread'], asserts every article has status == 'unread'.",
                inputs={"status": ["unread"]},
                assertions=["every_article_status_is_unread"],
            ),
            SemanticTest(
                name="read_article_count_matches_articles_length",
                description="Asserts article_count equals len(articles).",
                inputs={},
                assertions=["article_count_matches_articles_length"],
            ),
            SemanticTest(
                name="read_empty_store_returns_empty_articles_not_placeholder",
                description="When the saved-articles store has no rows, asserts articles=[] and a warning explains the empty state; no synthetic placeholder row appears.",
                inputs={"_mock": "store_empty"},
                assertions=[
                    "articles_empty_array",
                    "warning_mentions_empty_store",
                ],
            ),
        ],
    )


__all__ = ["read"]
