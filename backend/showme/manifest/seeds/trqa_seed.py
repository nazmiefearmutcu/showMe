"""TRQA — Transcript Q&A.

Ask natural-language questions against a transcript (text-pasted,
stored, or audio-anchored). Full transcripts from audio events require
Whisper for transcription and an LLM router for synthesis; without
those the pane falls back to a local extractive ranker over whatever
transcript text is available.
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
def trqa() -> FunctionManifest:
    return FunctionManifest(
        code="TRQA",
        name="Transcript Q&A",
        category=Category.NEWS_INTEL,
        intent=(
            "Ask natural-language questions against a transcript (text-pasted, stored, or "
            "audio-anchored). LLM router synthesizes evidence-cited answers; without an LLM "
            "router, a local extractive ranker returns top passages with confidence. Full "
            "audio transcripts require Whisper."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
        ],
        inputs=[
            InputSpec(
                name="text",
                label="Transcript text",
                control=ControlKind.TEXT,
                required=False,
                description="Pasted transcript text. Mutually exclusive with audio_url / audio_path.",
            ),
            InputSpec(
                name="audio_url",
                label="Audio URL",
                control=ControlKind.TEXT,
                required=False,
                description="HTTPS URL of an audio file. Requires Whisper for transcription.",
            ),
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="If text/audio not supplied, look up the most recent stored transcript for this symbol.",
            ),
            InputSpec(
                name="questions",
                label="Questions",
                control=ControlKind.MULTISELECT,
                required=True,
                description="Ordered list of natural-language questions to ask against the transcript.",
            ),
            InputSpec(
                name="max_tokens_per_answer",
                label="Max tokens / answer",
                control=ControlKind.NUMBER,
                required=False,
                description="LLM answer length cap.",
                min=64,
                max=2048,
                step=64,
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
                    DataMode.NOT_CONFIGURED.value,
                ],
            ),
        ],
        defaults={
            "text": "",
            "audio_url": "",
            "symbol": "",
            "questions": [],
            "max_tokens_per_answer": 512,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=["cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.MODELED,
                DataMode.CACHED_SNAPSHOT,
                DataMode.NOT_CONFIGURED,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=600, scope="per_input", persist=False),
        output_contract=OutputContract(
            must_have=["status", "text_chars", "answers"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="q", label="Question", kind="text"),
                ColumnSpec(key="a", label="Answer", kind="text"),
                ColumnSpec(key="evidence", label="Evidence", kind="text"),
                ColumnSpec(key="confidence", label="Conf", kind="number", format="%.2f"),
                ColumnSpec(key="model", label="Model", kind="tag"),
                ColumnSpec(key="cost_usd", label="$", kind="currency", format="%.4f"),
                ColumnSpec(key="tokens", label="Tokens", kind="number", format="%d"),
            ],
            sortable=False,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="text_chars", label="Chars", kind="kpi"),
                CardSlot(key="questions_count", label="Questions", kind="kpi"),
                CardSlot(key="answers_count", label="Answered", kind="kpi"),
                CardSlot(key="composer_mode", label="Composer", kind="badge"),
                CardSlot(key="total_cost_usd", label="Cost", kind="big_number", unit="USD"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TRQA resolves the transcript source in priority order — pasted text wins, then "
            "audio_url (requires Whisper to transcribe), then the most recent stored transcript "
            "for the input symbol. Once the transcript text is in hand, each question is "
            "answered through one of two composers. (1) When an LLM router is configured, the "
            "router is invoked per question with the transcript as context and a 'cite or omit' "
            "system prompt — every answer carries the verbatim evidence passage and a model + "
            "cost report. (2) When no LLM is configured (or provider_mode forces it), the local "
            "extractive ranker returns the top passage by BM25 score with confidence in [0,1]. "
            "Either composer requires Whisper to be configured for audio_url inputs — without "
            "Whisper the pane reports data_mode='not_configured' and answers=[] with a setup "
            "hint. The composer_mode field exposes which path was used so the analyst can audit. "
            "Cost is the literal LLM cost (0.0 for extractive)."
        ),
        field_dict={
            "status": FieldDef(description="ok / not_configured / no_text / provider_unavailable.", source="derived"),
            "text_chars": FieldDef(unit="chars", description="Length of the source transcript fed to the composer.", source="derived"),
            "answers[].q": FieldDef(description="Verbatim question echoed back.", source="input"),
            "answers[].a": FieldDef(description="Answer text — LLM synthesis or extractive top passage.", source="composer"),
            "answers[].evidence": FieldDef(description="Verbatim transcript passage cited as evidence.", source="composer"),
            "answers[].confidence": FieldDef(unit="[0,1]", description="Composer confidence (LLM logprobs proxy or BM25 normalized).", source="composer"),
            "answers[].model": FieldDef(description="LLM model id, or 'extractive' for the fallback.", source="composer"),
            "answers[].cost_usd": FieldDef(unit="USD", description="LLM call cost (0.0 for extractive).", source="router"),
            "answers[].tokens": FieldDef(unit="count", description="LLM total tokens (input + output).", source="router"),
            "composer_mode": FieldDef(description="llm_router / extractive — which composer answered.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="trqa_every_answer_has_evidence",
                description="Asserts every answer row has a non-empty evidence string that appears verbatim in the source transcript text.",
                inputs={"text": "AAPL CEO: We grew services revenue 12%. CFO: Margins improved 80bps.", "questions": ["What was services growth?"]},
                assertions=[
                    "every_answer_has_evidence",
                    "every_evidence_appears_verbatim_in_text",
                ],
            ),
            SemanticTest(
                name="trqa_whisper_missing_for_audio_returns_not_configured",
                description="With audio_url set but Whisper unavailable, asserts data_mode == 'not_configured', answers=[], and next_actions mentions Whisper setup.",
                inputs={"audio_url": "https://example.com/call.mp3", "questions": ["What was guidance?"], "_mock": "no_whisper"},
                assertions=[
                    "data_mode_equals_not_configured",
                    "answers_empty_array",
                    "next_actions_mentions_whisper",
                ],
            ),
            SemanticTest(
                name="trqa_composer_mode_is_reported",
                description="Asserts composer_mode in the payload is one of {'llm_router', 'extractive'}.",
                inputs={"text": "x", "questions": ["q"]},
                assertions=["composer_mode_in_llm_router_or_extractive"],
            ),
            SemanticTest(
                name="trqa_no_synthetic_answer_without_text",
                description="When text is empty AND no stored transcript can be resolved AND no audio, asserts status reports the missing source and answers=[] — no hallucinated answer.",
                inputs={"questions": ["q"]},
                assertions=[
                    "status_reports_missing_transcript",
                    "answers_empty_array",
                ],
            ),
        ],
    )


__all__ = ["trqa"]
