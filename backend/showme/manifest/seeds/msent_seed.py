"""MSENT — Market Sentiment dashboard.

Market-wide sentiment indicators as Awareness reports them: CNN Fear & Greed, crypto Fear &
Greed, the VIX term structure and ApeWisdom social-buzz movers. Null sections stay null.
"""
from __future__ import annotations

from ..enums import (
    Category,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    CachingPolicy,
    FieldDef,
    FunctionManifest,
    InputSpec,
    OutputContract,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
)


@manifest()
def msent() -> FunctionManifest:
    return FunctionManifest(
        code="MSENT",
        name="Market Sentiment",
        category=Category.NEWS_INTEL,
        intent=(
            "Market-wide sentiment dashboard: CNN Fear & Greed with its seven components and history, "
            "crypto Fear & Greed, the VIX term structure with contango or backwardation, and social "
            "buzz movers. Every reading is an Awareness value with its own timestamp."
        ),
        asset_classes=[],
        inputs=[
            InputSpec(
                name="history_days",
                label="History (days)",
                control=ControlKind.NUMBER,
                required=False,
                description="Days of Fear & Greed and VIX history to return, from 1 to 365.",
                min=1,
                max=365,
                step=1,
            ),
        ],
        defaults={
            "history_days": 90,
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
        caching=CachingPolicy(ttl_seconds=300, scope="global", persist=False),
        output_contract=OutputContract(
            must_have=["status", "cnn", "crypto", "vix", "social", "meta"],
            rows=False,
            series=True,
            cards=False,
            warnings=True,
            next_actions=True,
        ),
        methodology=(
            "MSENT passes through the Awareness market-sentiment snapshot without transformation. "
            "cnn holds the CNN Fear & Greed score (0 to 100), rating, previous close, one-week, "
            "one-month and one-year comparisons, the seven component scores and a daily history. "
            "crypto holds the crypto Fear & Greed score, rating and history. vix holds the VIX, "
            "VIX9D and VIX3M levels, the term ratio VIX/VIX3M and its structure (contango when the "
            "ratio is below 1, backwardation when above) with a daily history. social lists the "
            "ApeWisdom stock and crypto mention leaders with rank, mentions and 24-hour change. "
            "History is trimmed to history_days. A section Awareness returns as null stays null and "
            "is shown as no data; no default gauge value is ever substituted. When Awareness is down "
            "the function returns provider_unavailable."
        ),
        field_dict={
            "cnn.score": FieldDef(unit="0-100", description="CNN Fear & Greed index value.", source="awareness"),
            "cnn.components": FieldDef(description="Seven CNN component scores with their own timestamps.", source="awareness"),
            "crypto.score": FieldDef(unit="0-100", description="Crypto Fear & Greed index value.", source="awareness"),
            "vix.term_ratio": FieldDef(description="VIX divided by VIX3M.", source="awareness"),
            "vix.structure": FieldDef(description="contango or backwardation, from the term ratio.", source="awareness"),
            "social.stocks": FieldDef(description="ApeWisdom stock mention leaders.", source="awareness"),
            "social.crypto": FieldDef(description="ApeWisdom crypto mention leaders.", source="awareness"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="msent_null_sections_stay_null",
                description="When Awareness returns a null section, asserts that section is null in the payload.",
                inputs={"_mock": "vix_null"},
                assertions=["vix_is_null", "no_default_gauge_value"],
            ),
            SemanticTest(
                name="msent_history_trimmed_to_history_days",
                description="Asserts every returned history point falls inside the requested history_days.",
                inputs={"history_days": 30},
                assertions=["history_points_within_window"],
            ),
            SemanticTest(
                name="msent_awareness_down_is_provider_unavailable",
                description="When awareness cannot answer, asserts provider_unavailable with null sections.",
                inputs={"_mock": "awareness_down"},
                assertions=["status_provider_unavailable", "sections_null"],
            ),
        ],
    )


__all__ = ["msent"]
