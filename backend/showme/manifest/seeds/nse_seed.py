"""NSE — News Search Engine (Awareness full-text search over sourced stories).

Backend handler is ``engine/functions/news/nse.py``. Full-text search runs in awareness,
so company names ("Berkshire") and ticker-style words both resolve without a local index.
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
            "Search sourced news by company name, ticker or topic words over a chosen window; "
            "rows are publisher stories with sentiment and quality, and a hidden-rows note when "
            "the quality floor hides matches."
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
                name="q",
                label="Search",
                control=ControlKind.TEXT,
                required=False,
                description="Full-text search, for example a company name such as Berkshire or a topic phrase.",
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Optional entity filter, used when no search text is given.",
            ),
            InputSpec(
                name="hours",
                label="Window (hours)",
                control=ControlKind.NUMBER,
                required=False,
                description="Look-back window in hours (1 to 1440).",
                min=1.0,
                max=1440.0,
                step=1.0,
                unit="hours",
            ),
            InputSpec(
                name="min_quality",
                label="Quality floor",
                control=ControlKind.SELECT,
                required=False,
                description="Lowest quality label kept. Standard by default; low must be chosen explicitly.",
                options=["premium", "standard", "low"],
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
        ],
        defaults={"q": "", "symbol": "", "hours": 720, "min_quality": "standard", "limit": 50},
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
                ColumnSpec(key="title", label="Headline", kind="text"),
                ColumnSpec(key="symbols", label="Symbols", kind="tag"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="quality_label", label="Quality", kind="tag"),
                ColumnSpec(key="url", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="count", label="Matches", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "NSE sends the search text to the awareness full-text index over the sourced news "
            "store (titles, summaries and excerpts), restricted to the hours window and the "
            "quality floor, collapsed to one row per story. Without search text it filters by the "
            "entity symbol. Sentiment is labelled per row by awareness (sentiment_model names FinBERT "
            "ProsusAI/finbert or the lexicon fallback aw-fin-1) and quality is the awareness "
            "quality gate. If nothing matches at standard quality the rows stay hidden: hidden_note "
            "counts the lower-quality matches and relax suggests min_quality low. The quality "
            "floor is never lowered silently."
        ),
        field_dict={
            "rows[].published_at": FieldDef(unit="iso8601", description="Publisher timestamp (UTC).", source="feed"),
            "rows[].publisher": FieldDef(description="Publisher name.", source="feed"),
            "rows[].title": FieldDef(description="Headline as published.", source="feed"),
            "rows[].url": FieldDef(unit="url", description="Link to the publisher article.", source="feed"),
            "rows[].sentiment": FieldDef(description="positive, negative or neutral (awareness label; model named in sentiment_model).", source="finbert"),
            "rows[].quality_label": FieldDef(description="premium, standard or low.", source="awareness"),
            "hidden_note": FieldDef(description="Count of matches hidden by the quality floor.", source="awareness"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        semantic_tests=[
            SemanticTest(
                name="nse_company_name_search_returns_sourced_rows",
                description="A company-name query returns only rows with a publisher URL.",
                inputs={"q": "Berkshire"},
                assertions=["every_row_has_url", "rows_match_query_text_or_entity"],
            ),
            SemanticTest(
                name="nse_quality_floor_not_silently_lowered",
                description="With no rows at standard, hidden_note explains the floor and relax is min_quality low; rows stay empty.",
                inputs={"q": "obscure", "min_quality": "standard"},
                assertions=["rows_empty_at_standard", "relax_hint_present", "hidden_note_present"],
            ),
            SemanticTest(
                name="nse_empty_query_is_input_required",
                description="A call with neither q nor symbol returns status input_required, never a broad news dump.",
                inputs={},
                assertions=["status_input_required"],
            ),
        ],
    )


__all__ = ["nse"]
