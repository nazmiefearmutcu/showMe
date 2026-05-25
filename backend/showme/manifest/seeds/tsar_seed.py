"""TSAR — Transcript Sentiment Analyzer.

Run FinBERT (and optional XSEN RoBERTa) over a transcript and surface
per-section / per-speaker / per-utterance sentiment. The dominant tone
of the call, the polarity by speaker role (mgmt vs analyst), and a
top-quote ladder for each polarity bucket. Full audio transcripts
require Whisper.
"""
from __future__ import annotations

from ..enums import (
    AssetClass,
    Category,
    ChartKind,
    ControlKind,
    DataMode,
)
from ..registry import manifest
from ..spec import (
    AxisSpec,
    CachingPolicy,
    CardSchema,
    CardSlot,
    ChartGrammar,
    ColumnSpec,
    FieldDef,
    Formula,
    FunctionManifest,
    InputSpec,
    OutputContract,
    PaneGrammar,
    ProvenanceSpec,
    ProviderChain,
    SemanticTest,
    TableSchema,
)


@manifest()
def tsar() -> FunctionManifest:
    return FunctionManifest(
        code="TSAR",
        name="Transcript Sentiment Analyzer",
        category=Category.NEWS_INTEL,
        intent=(
            "Score a transcript with FinBERT (and optional XSEN RoBERTa) and surface the "
            "per-section / per-speaker / per-utterance sentiment — dominant call tone, polarity "
            "by speaker role (mgmt vs analyst), and a top-quote ladder for each polarity. Full "
            "audio transcripts require Whisper for transcription."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.ETF,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Look up the most recent stored transcript for this symbol when text is not pasted.",
            ),
            InputSpec(
                name="text",
                label="Transcript text",
                control=ControlKind.TEXT,
                required=False,
                description="Pasted transcript text; mutually exclusive with symbol/quarter lookup.",
            ),
            InputSpec(
                name="quarter",
                label="Quarter",
                control=ControlKind.SELECT,
                required=False,
                description="Stored-transcript lookup helper.",
            ),
            InputSpec(
                name="models",
                label="Models",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Sentiment models to run.",
                options=["finbert", "xsen_roberta"],
            ),
            InputSpec(
                name="speaker_roles",
                label="Speaker roles",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Restrict polarity rollups to these roles.",
                options=["management", "analyst", "operator", "all"],
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
            "symbol": "",
            "text": "",
            "quarter": "",
            "models": ["finbert"],
            "speaker_roles": ["all"],
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
        caching=CachingPolicy(ttl_seconds=600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["status", "summary", "speaker_rollups", "utterances"],
            rows=True,
            series=True,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        chart_grammar=ChartGrammar(
            kind=ChartKind.BAR_LADDER,
            x_axis=AxisSpec(type="numeric", unit="score", label="Sentiment"),
            y_axis=AxisSpec(type="category", label="Speaker"),
            panes=[
                PaneGrammar(name="speaker_polarity", series_kind="bar", height_pct=100),
            ],
            overlay_support=False,
            compare_support=False,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="position", label="#", kind="number", format="%d", width_hint=40),
                ColumnSpec(key="section", label="Section", kind="tag"),
                ColumnSpec(key="speaker", label="Speaker", kind="text"),
                ColumnSpec(key="role", label="Role", kind="tag"),
                ColumnSpec(key="utterance", label="Utterance", kind="text"),
                ColumnSpec(key="sentiment", label="Sentiment", kind="tag"),
                ColumnSpec(key="score", label="Score", kind="number", format="%.2f"),
                ColumnSpec(key="model", label="Model", kind="tag"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="dominant_tone", label="Tone", kind="big_number"),
                CardSlot(key="net_score", label="Net", kind="kpi"),
                CardSlot(key="management_score", label="Mgmt", kind="kpi"),
                CardSlot(key="analyst_score", label="Analyst", kind="kpi"),
                CardSlot(key="utterance_count", label="Utterances", kind="kpi"),
                CardSlot(key="model_set", label="Models", kind="badge"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TSAR resolves the transcript source identically to TRAN/TRQA — pasted text wins, "
            "then (symbol, quarter) lookup in the transcripts_archive, then audio_url via "
            "Whisper. Each utterance is scored by every model in the input set: FinBERT returns "
            "(label, score) per utterance from the bundled checkpoint; xsen_roberta runs the "
            "X-tuned RoBERTa (reused from XSEN) on the utterance text. Per-utterance score is "
            "the normalized FinBERT margin (P(pos) - P(neg)) in [-1, +1]; xsen score is the "
            "same range. Speaker rollups aggregate utterance scores by role with utterance-"
            "weighted mean. The dominant_tone string is derived from net_score with hysteresis "
            "thresholds (positive >= +0.12, negative <= -0.12, else neutral). When the "
            "underlying audio requires Whisper and Whisper is missing, data_mode='not_configured' "
            "and utterances=[] with a setup hint — never a fabricated sentiment."
        ),
        formula_dict={
            "utterance_score": Formula(
                expression=r"score = P(pos) - P(neg)",
                variables={
                    "P(pos)": "FinBERT posterior probability of positive class",
                    "P(neg)": "FinBERT posterior probability of negative class",
                },
                notes="Per-utterance signed sentiment in [-1, +1].",
            ),
            "speaker_rollup": Formula(
                expression=r"rollup_{role} = \frac{\sum_{i \in role} score_i \cdot len_i}{\sum_{i \in role} len_i}",
                variables={
                    "score_i": "Per-utterance score",
                    "len_i": "Utterance length in chars (weight)",
                },
                notes="Char-length weighted mean per speaker role.",
            ),
        },
        field_dict={
            "status": FieldDef(description="ok / not_configured / no_text.", source="derived"),
            "summary.dominant_tone": FieldDef(description="positive / negative / neutral derived from net_score with hysteresis thresholds.", source="derived"),
            "summary.net_score": FieldDef(unit="[-1,+1]", description="Char-length weighted mean of all utterance scores.", source="computed"),
            "summary.utterance_count": FieldDef(unit="count", description="Number of utterances scored.", source="derived"),
            "speaker_rollups[].role": FieldDef(description="management / analyst / operator.", source="archive"),
            "speaker_rollups[].score": FieldDef(unit="[-1,+1]", description="Char-length weighted mean score for this role.", source="computed"),
            "speaker_rollups[].count": FieldDef(unit="count", description="Utterances by this role.", source="derived"),
            "utterances[].score": FieldDef(unit="[-1,+1]", description="Per-utterance sentiment score.", source="model"),
            "utterances[].sentiment": FieldDef(description="positive / negative / neutral tag from the score.", source="derived"),
            "utterances[].model": FieldDef(description="finbert / xsen_roberta — which model produced the score.", source="model"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="tsar_speaker_rollups_are_length_weighted",
                description="Asserts each speaker_rollups[].score equals the char-length weighted mean of that role's utterance scores within 1e-6.",
                inputs={"text": "CEO: We grew revenue 20% YoY. CFO: Margins expanded.", "models": ["finbert"]},
                assertions=["speaker_rollups_score_matches_length_weighted_mean"],
            ),
            SemanticTest(
                name="tsar_dominant_tone_uses_hysteresis_thresholds",
                description="Asserts dominant_tone == 'neutral' when |net_score| < 0.12, else matches the sign of net_score.",
                inputs={},
                assertions=["dominant_tone_uses_hysteresis_thresholds"],
            ),
            SemanticTest(
                name="tsar_whisper_missing_returns_not_configured",
                description="With audio_url requiring Whisper and Whisper missing, asserts data_mode == 'not_configured' and utterances=[] with a setup hint in next_actions.",
                inputs={"_mock": "no_whisper_audio"},
                assertions=[
                    "data_mode_equals_not_configured",
                    "utterances_empty_array",
                    "next_actions_mentions_whisper",
                ],
            ),
            SemanticTest(
                name="tsar_model_id_present_per_utterance",
                description="Asserts every utterance score row carries a model id in {'finbert', 'xsen_roberta'} so provenance is auditable.",
                inputs={"text": "x", "models": ["finbert"]},
                assertions=["every_utterance_has_model_id"],
            ),
        ],
    )


__all__ = ["tsar"]
