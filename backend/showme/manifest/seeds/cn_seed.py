"""CN — Company News (sourced stories for one symbol).

Backend handler is ``engine/functions/news/cn.py``. News rows only: no price or market
rows. Symbols are normalised to the awareness entity id before the query.
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
def cn() -> FunctionManifest:
    return FunctionManifest(
        code="CN",
        name="Company News",
        category=Category.NEWS_INTEL,
        intent=(
            "Sourced news for one company, ETF or crypto asset: one row per story at quality "
            "standard or better, with publisher, sentiment and importance. News only; no price "
            "or market rows."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
            AssetClass.CRYPTO,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=True,
                description="Ticker or coin, for example AAPL, BRK.B, THYAO.IS or BTC (pairs like BTCUSDT normalise to BTC).",
            ),
            InputSpec(
                name="hours",
                label="Window (hours)",
                control=ControlKind.NUMBER,
                required=False,
                description="Look-back window in hours (1 to 720).",
                min=1.0,
                max=720.0,
                step=1.0,
                unit="hours",
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
        defaults={"hours": 168, "limit": 50},
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
            must_have=["status", "symbol", "rows", "meta"],
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
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="importance", label="Importance", kind="number", format="%.0f"),
                ColumnSpec(key="url", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="count", label="Stories", kind="kpi"),
                CardSlot(key="symbol", label="Symbol", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "Awareness collects publisher articles, links each one to the entities it names "
            "(symbols), scores quality (publisher tier, timestamp precision, entity confidence, "
            "topic evidence), labels sentiment per row (sentiment_model names FinBERT ProsusAI/finbert "
            "or the lexicon fallback aw-fin-1), scores importance "
            "0-100 and collapses duplicate reports into stories. CN asks for the symbol's entity "
            "at quality standard or better within the hours window. The symbol is normalised first: "
            "pair suffixes are removed (BTCUSDT and BTC-USD become BTC), BRK.B becomes BRK-B, and "
            "the BIST .IS suffix is kept. No market, price or exchange rows are included."
        ),
        field_dict={
            "rows[].published_at": FieldDef(unit="iso8601", description="Publisher timestamp (UTC).", source="feed"),
            "rows[].publisher": FieldDef(description="Publisher name.", source="feed"),
            "rows[].title": FieldDef(description="Headline as published.", source="feed"),
            "rows[].url": FieldDef(unit="url", description="Link to the publisher article.", source="feed"),
            "rows[].sentiment": FieldDef(description="positive, negative or neutral (awareness label; model named in sentiment_model).", source="finbert"),
            "rows[].importance": FieldDef(unit="0-100", description="Awareness importance score.", source="awareness"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        semantic_tests=[
            SemanticTest(
                name="cn_symbol_normalised_to_entity_id",
                description="BTCUSDT, BTC-USD and BRK.B are sent to awareness as BTC and BRK-B.",
                inputs={"symbol": "BTCUSDT"},
                assertions=["symbols_query_is_BTC", "BRK_B_becomes_BRK-B"],
            ),
            SemanticTest(
                name="cn_no_market_rows",
                description="Rows are news stories only; no price, ticker or exchange rows are returned.",
                inputs={"symbol": "AAPL"},
                assertions=["every_row_has_publisher_and_url"],
            ),
            SemanticTest(
                name="cn_empty_is_not_ok",
                description="A symbol with no stories in the window returns status empty, not ok.",
                inputs={"symbol": "ZZZZ", "hours": 1},
                assertions=["status_empty_when_no_rows"],
            ),
        ],
    )


__all__ = ["cn"]
