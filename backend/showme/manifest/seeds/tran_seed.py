"""TRAN — Earnings Transcript or Release Viewer.

Reader pane for earnings-call (and other investor-event) transcripts or the
8-K earnings release. Symbol → 8-K lookup uses keyless SEC EDGAR filings; a
pasted or archived transcript is served from the internal transcripts_archive
when present. Full audio
transcription requires Whisper to be wired up; without it the pane
serves whatever stored transcripts are available and reports
data_mode=not_configured for missing rows.
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
def tran() -> FunctionManifest:
    return FunctionManifest(
        code="TRAN",
        name="Earnings Transcript or Release",
        category=Category.NEWS_INTEL,
        intent=(
            "Reader pane for earnings-call (and other investor-event) transcripts, or the SEC "
            "8-K earnings release when no transcript exists. Symbol → 8-K lookup uses keyless "
            "SEC EDGAR filings; stored transcripts come from the internal transcripts_archive. "
            "Full audio transcription requires Whisper for "
            "events without a pre-supplied transcript; without Whisper the pane serves stored "
            "transcripts and reports the not-configured rows honestly."
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
                required=True,
                description="Equity ticker. Looked up against SEC EDGAR 8-K earnings filings.",
            ),
            InputSpec(
                name="quarter",
                label="Quarter",
                control=ControlKind.SELECT,
                required=False,
                description="Fiscal quarter (e.g. Q1 FY26). The 8-K whose report date releases that fiscal quarter is matched using the company's SEC fiscal year end; no fiscal year end or no match is an empty state. Empty = newest earnings 8-K.",
            ),
            InputSpec(
                name="speaker_filter",
                label="Speaker filter",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Render only utterances by these speakers.",
            ),
            InputSpec(
                name="section",
                label="Section",
                control=ControlKind.SELECT,
                required=False,
                description="Restrict to prepared remarks or Q&A.",
                options=["all", "prepared_remarks", "qa"],
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
                    DataMode.NOT_CONFIGURED.value,
                ],
            ),
        ],
        defaults={
            "symbol": "AAPL",
            "quarter": "",
            "speaker_filter": [],
            "section": "all",
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
        },
        provider_chain=ProviderChain(
            primary="sec_edgar",
            fallbacks=["internal", "cached_snapshot"],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
                DataMode.CACHED_SNAPSHOT,
                DataMode.MODELED,
                DataMode.NOT_CONFIGURED,
                DataMode.PROVIDER_UNAVAILABLE,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["symbol", "status", "event", "utterances", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="position", label="#", kind="number", format="%d", width_hint=48),
                ColumnSpec(key="section", label="Section", kind="tag"),
                ColumnSpec(key="speaker", label="Speaker", kind="text"),
                ColumnSpec(key="role", label="Role", kind="tag"),
                ColumnSpec(key="utterance", label="Utterance", kind="text"),
                ColumnSpec(key="timestamp", label="t", kind="duration"),
            ],
            sortable=False,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="symbol", label="Symbol", kind="badge"),
                CardSlot(key="quarter", label="Quarter", kind="badge"),
                CardSlot(key="event_date", label="Event Date", kind="timestamp"),
                CardSlot(key="utterance_count", label="Utterances", kind="kpi"),
                CardSlot(key="speakers_count", label="Speakers", kind="kpi"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "TRAN resolves the symbol to its 8-K earnings exhibit using the keyless SEC EDGAR "
            "submissions index. A requested fiscal quarter is matched to the 8-K that releases it, "
            "using the report date and the company's SEC fiscal year end; event.quarter_basis "
            "states this derivation. "
            "If a transcript already exists in transcripts_archive for that "
            "event id, it is served straight from the archive. If no transcript exists and the "
            "event has an audio_url, TRAN attempts to invoke Whisper to transcribe the audio — "
            "this requires Whisper to be installed and configured (engine/services/whisper). "
            "When Whisper is NOT configured, the pane reports data_mode='not_configured', "
            "surfaces a setup hint in next_actions, and returns utterances=[] for that event — "
            "it never fabricates a transcript. Stored transcripts are returned as an ordered "
            "list of utterances with {section, speaker, role, utterance, timestamp_seconds}. "
            "Section/speaker filters apply post-load. The pane is read-only — ingestion is "
            "handled by /api/transcripts/ingest, not by TRAN itself."
        ),
        field_dict={
            "symbol": FieldDef(description="Echoed input symbol.", source="input"),
            "status": FieldDef(description="ok / not_configured / provider_unavailable.", source="derived"),
            "event": FieldDef(description="Earnings event metadata (quarter, quarter_basis, event_date, audio_url, source).", source="sec_edgar / archive"),
            "utterances[].section": FieldDef(description="prepared_remarks / qa.", source="archive"),
            "utterances[].speaker": FieldDef(description="Speaker name as captured in the transcript.", source="archive"),
            "utterances[].role": FieldDef(description="Role/title (CEO, CFO, Analyst:Firm).", source="archive"),
            "utterances[].utterance": FieldDef(description="Verbatim utterance text.", source="archive"),
            "utterances[].timestamp_seconds": FieldDef(unit="seconds", description="Offset from event start (when available).", source="archive"),
            "data_mode": FieldDef(description="not_configured when Whisper is required for fresh events and is missing.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="tran_stored_transcript_returns_utterances",
                description="For (symbol, quarter) where the archive holds a transcript, asserts utterances is non-empty and each row has section, speaker, utterance.",
                inputs={"symbol": "AAPL", "quarter": "Q4 FY25", "_mock": "archive_has_transcript"},
                assertions=[
                    "utterances_non_empty",
                    "every_utterance_has_section_speaker_text",
                ],
            ),
            SemanticTest(
                name="tran_whisper_missing_reports_not_configured",
                description="For an event with an audio_url but no stored transcript and Whisper unavailable, asserts data_mode == 'not_configured', utterances=[], and next_actions lists a Whisper setup hint.",
                inputs={"symbol": "AAPL", "quarter": "Q4 FY25", "_mock": "no_whisper"},
                assertions=[
                    "data_mode_equals_not_configured",
                    "utterances_empty_array",
                    "next_actions_mentions_whisper",
                ],
            ),
            SemanticTest(
                name="tran_speaker_filter_applies",
                description="With speaker_filter=['Tim Cook'], asserts every utterance has speaker matching 'Tim Cook'.",
                inputs={"symbol": "AAPL", "speaker_filter": ["Tim Cook"]},
                assertions=["every_utterance_speaker_in_filter"],
            ),
            SemanticTest(
                name="tran_no_synthetic_transcript",
                description="Asserts utterances rows are never fabricated — every utterance text exactly matches the archive row.",
                inputs={"_mock": "archive_has_transcript"},
                assertions=["every_utterance_text_matches_archive_verbatim"],
            ),
        ],
    )


__all__ = ["tran"]
