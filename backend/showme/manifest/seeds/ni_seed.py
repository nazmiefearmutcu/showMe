"""NI — News by Topic (sourced stories for one topic preset).

Backend handler is ``engine/functions/news/ni.py``. Each preset maps onto awareness
taxonomy tags (topics and asset classes); the mapping is listed in the methodology.
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
def ni() -> FunctionManifest:
    return FunctionManifest(
        code="NI",
        name="News by Topic",
        category=Category.NEWS_INTEL,
        intent=(
            "Sourced news for one topic preset (banks, earnings, Fed, chips, oil, tech, macro, "
            "war, M&A, IPO, crypto): one row per story from the awareness taxonomy, with publisher, "
            "sentiment, importance and quality shown on every row."
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
                name="topic",
                label="Topic",
                control=ControlKind.SELECT,
                required=True,
                description="Topic preset: BANKS, EARN, FED, CHIPS, OIL, TECH, MACRO, WAR, M&A, IPO or CRYPTO.",
                options=["BANKS", "EARN", "FED", "CHIPS", "OIL", "TECH", "MACRO", "WAR", "M&A", "IPO", "CRYPTO"],
            ),
            InputSpec(
                name="hours",
                label="Window (hours)",
                control=ControlKind.NUMBER,
                required=False,
                description="Look-back window in hours (1 to 168).",
                min=1.0,
                max=168.0,
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
        defaults={"topic": "MACRO", "hours": 48, "limit": 50},
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
            must_have=["status", "rows", "topic", "meta"],
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
                ColumnSpec(key="importance", label="Importance", kind="number", format="%.0f"),
                ColumnSpec(key="url", label="", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="count", label="Stories", kind="kpi"),
                CardSlot(key="topic", label="Topic", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "Awareness tags every item with taxonomy topics and asset classes (rule-based, "
            "alias matching). A preset is a filter on those tags: topics are OR-ed inside the "
            "preset, asset classes are AND-ed with them. BANKS = funding_liquidity, credit_stress, "
            "earnings within equities; CHIPS = supply_chain, trade_tariffs, product_launch within "
            "equities; TECH = product_launch, cyber_outage within equities (approximations: "
            "awareness has no bank or semiconductor tag); EARN = earnings, guidance; FED = "
            "central_bank; OIL = energy; MACRO = inflation, employment, growth_recession, "
            "fiscal_policy; WAR = geopolitics, sanctions; M&A = m_and_a; IPO = ipo; CRYPTO = "
            "crypto_market within the crypto asset class. Only quality standard or better is kept. "
            "importance is the awareness 0-100 score; sentiment is labelled by awareness per row "
            "(the row's sentiment_model names the model: FinBERT ProsusAI/finbert, or the lexicon "
            "fallback aw-fin-1). An unknown topic shows MACRO and says so in hidden_note."
        ),
        field_dict={
            "rows[].published_at": FieldDef(unit="iso8601", description="Publisher timestamp (UTC).", source="feed"),
            "rows[].publisher": FieldDef(description="Publisher name.", source="feed"),
            "rows[].title": FieldDef(description="Headline as published.", source="feed"),
            "rows[].url": FieldDef(unit="url", description="Link to the publisher article.", source="feed"),
            "rows[].sentiment": FieldDef(description="positive, negative or neutral (awareness label; model named in sentiment_model).", source="finbert"),
            "rows[].importance": FieldDef(unit="0-100", description="Awareness importance score (a number, not a tag).", source="awareness"),
            "rows[].story_size": FieldDef(unit="count", description="Reports collapsed into this story.", source="awareness"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        semantic_tests=[
            SemanticTest(
                name="ni_importance_is_score_0_100",
                description="importance on every row is the awareness 0-100 numeric score, never a tag.",
                inputs={"topic": "EARN"},
                assertions=["importance_is_number_between_0_and_100"],
            ),
            SemanticTest(
                name="ni_every_row_matches_topic_tags",
                description="Each row carries at least one of the preset's topic tags or asset-class tags.",
                inputs={"topic": "FED"},
                assertions=["row_topics_intersect_preset"],
            ),
            SemanticTest(
                name="ni_unknown_topic_is_disclosed",
                description="An unknown topic falls back to MACRO and hidden_note names the requested topic.",
                inputs={"topic": "NOPE"},
                assertions=["topic_falls_back_to_macro", "hidden_note_names_requested_topic"],
            ),
        ],
    )


__all__ = ["ni"]
