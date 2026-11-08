"""TLDR — TL;DR Summarizer.

Composes a 5-bullet TL;DR for the portfolio + watchlist day from live
quotes and recent headlines. Every bullet cites the underlying evidence
row — no synthetic prose, no fabricated quotes. When no LLM is wired
up, falls back to a deterministic extractive summarizer over the same
evidence set.
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
def tldr() -> FunctionManifest:
    return FunctionManifest(
        code="TLDR",
        name="Daily TL;DR",
        category=Category.NEWS_INTEL,
        intent=(
            "5-bullet TL;DR for the portfolio + watchlist day, composed from live quotes and "
            "recent headlines. Every bullet cites the underlying evidence row — no synthetic "
            "prose, no fabricated quotes. Falls back to a deterministic extractive summarizer "
            "when no LLM is configured."
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
                name="symbols",
                label="Symbols",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Symbols to summarize. Empty = read from PortfolioState + fallback default set.",
            ),
            InputSpec(
                name="bullets",
                label="Bullets",
                control=ControlKind.NUMBER,
                required=False,
                description="How many bullets to render (3..8).",
                min=3,
                max=8,
                step=1,
            ),
            InputSpec(
                name="evidence_per_bullet",
                label="Evidence rows / bullet",
                control=ControlKind.NUMBER,
                required=False,
                description="Maximum evidence citations per bullet.",
                min=1,
                max=5,
                step=1,
            ),
            InputSpec(
                name="timeout",
                label="Compose timeout",
                control=ControlKind.NUMBER,
                required=False,
                description="Hard ceiling for LLM + extraction roundtrip in seconds.",
                min=3.0,
                max=15.0,
                step=0.5,
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
            "symbols": [],
            "bullets": 5,
            "evidence_per_bullet": 2,
            "timeout": 8.0,
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
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["status", "markdown", "bullets", "symbols"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="position", label="#", kind="number", format="%d", width_hint=40),
                ColumnSpec(key="bullet_text", label="Bullet", kind="text"),
                ColumnSpec(key="evidence_count", label="Cites", kind="number", format="%d"),
                ColumnSpec(key="evidence_links", label="Evidence", kind="action"),
            ],
            sortable=False,
            filterable=False,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbols_count", label="Symbols", kind="kpi"),
                CardSlot(key="bullets_count", label="Bullets", kind="kpi"),
                CardSlot(key="evidence_count_total", label="Citations", kind="kpi"),
                CardSlot(key="composer_mode", label="Composer", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TLDR composes the summary in two phases. (1) Evidence collection: for each symbol, "
            "pull the current quote snapshot via fetch_quote_snapshot (the same path /api/quote "
            "uses, so the TL;DR cannot disagree with the WATCH ticker) and the top recent "
            "headlines via the TOP feed. (2) Bullet composition: bullets[] is built deterministically "
            "from those rows (composer_mode = extractive): top up-movers, top down-movers, quote "
            "coverage, news themes and calendar items, each citing the rows it was built from. "
            "The bullets input caps the count (3..8) and evidence_per_bullet caps the rows cited per "
            "bullet (1..5). evidence_links holds only the HTTP(S) URLs a row carries; quote and "
            "calendar rows carry none, so their bullets have an empty evidence_links. A candidate "
            "with no evidence rows is omitted, never filled in. When an LLM answers, it writes the "
            "markdown briefing only; bullets[] stays extractive. The summary NEVER invents prose or "
            "a bullet without an evidence row behind it."
        ),
        field_dict={
            "status": FieldDef(description="ok / reference / provider_unavailable.", source="derived"),
            "markdown": FieldDef(description="Markdown briefing: the LLM text when it answered, otherwise the template built from the same rows.", source="composed"),
            "bullets[].bullet_text": FieldDef(description="Bullet text built from the cited evidence rows (no LLM prose).", source="composer"),
            "bullets[].evidence": FieldDef(description="The evidence rows (quote, news or calendar) this bullet cites.", source="composer"),
            "bullets[].evidence_links": FieldDef(description="HTTP(S) URLs carried by the cited rows. Empty for quote and calendar evidence, which have no per-row URL.", source="composer"),
            "bullets[].evidence_count": FieldDef(unit="count", description="Number of evidence rows cited.", source="derived"),
            "bullets[].symbols": FieldDef(description="Symbols this bullet touches.", source="composer"),
            "composer_mode": FieldDef(description="llm / extractive — which path produced the bullets.", source="derived"),
            "symbols": FieldDef(description="Effective symbol set used.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="tldr_every_bullet_has_evidence_link",
                description="Asserts every bullet in `bullets[]` cites at least one evidence row (evidence_count >= 1) and every evidence link that is present is http(s). The summary must cite, never summarize without evidence.",
                inputs={"symbols": ["AAPL", "MSFT"]},
                assertions=[
                    "every_bullet_cites_at_least_one_evidence_row",
                    "every_evidence_link_is_http_or_https",
                ],
            ),
            SemanticTest(
                name="tldr_no_evidence_no_bullet",
                description="When no headlines or quote evidence is available for a symbol, asserts no bullet is fabricated and a warning explains the empty evidence set.",
                inputs={"_mock": "no_evidence"},
                assertions=[
                    "bullets_empty_array",
                    "warning_mentions_empty_evidence",
                ],
            ),
            SemanticTest(
                name="tldr_composer_mode_is_reported",
                description="Asserts composer_mode in the payload is one of {'llm', 'extractive'} so the caller can audit which path produced the prose.",
                inputs={},
                assertions=["composer_mode_in_llm_or_extractive"],
            ),
            SemanticTest(
                name="tldr_quote_matches_quote_endpoint",
                description="When bullets cite a price/quote, asserts the cited value equals the /api/quote snapshot for the same symbol (no drift).",
                inputs={"symbols": ["AAPL"]},
                assertions=["bullet_quote_matches_quote_endpoint_within_eps"],
            ),
        ],
    )


__all__ = ["tldr"]
