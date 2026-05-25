"""AV — Audio / Video Archive Viewer.

Playable archive of investor-relevant audio and video — earnings call
audio, central bank pressers, conference replays, podcast episodes —
backed by the internal media store. Items are real, time-anchored,
playable resources (URL + duration + transcript fallback), not a
placeholder list of "coming soon" rows.
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
def av() -> FunctionManifest:
    return FunctionManifest(
        code="AV",
        name="Audio / Video Archive",
        category=Category.NEWS_INTEL,
        intent=(
            "Playable archive of investor-relevant audio and video — earnings call audio, "
            "central bank pressers, conference replays, podcast episodes — with real, "
            "time-anchored URLs, durations, transcript availability, and one-click open. "
            "This is a playable archive, not a placeholder list of 'coming soon' rows."
        ),
        asset_classes=[
            AssetClass.EQUITY,
            AssetClass.CRYPTO,
            AssetClass.RATE,
            AssetClass.FX,
        ],
        inputs=[
            InputSpec(
                name="symbol",
                label="Symbol",
                control=ControlKind.SYMBOL_PICKER,
                required=False,
                description="Filter the archive by symbol; empty = global archive.",
            ),
            InputSpec(
                name="media_type",
                label="Media type",
                control=ControlKind.MULTISELECT,
                required=False,
                description="Filter by media kind; empty = all.",
                options=["earnings_call", "central_bank_presser", "conference", "podcast", "interview"],
            ),
            InputSpec(
                name="date_range",
                label="Date range",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Restrict to items in this window; empty = last 90 days.",
            ),
            InputSpec(
                name="has_transcript",
                label="Has transcript",
                control=ControlKind.BOOLEAN,
                required=False,
                description="Only show items with a stored transcript.",
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
            "symbol": "",
            "media_type": [],
            "date_range": "last_90d",
            "has_transcript": False,
            "provider_mode": DataMode.LIVE_OFFICIAL.value,
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
        caching=CachingPolicy(ttl_seconds=300, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["as_of", "items", "data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="event_date", label="Date", kind="datetime", format="yyyy-MM-dd HH:mm"),
                ColumnSpec(key="symbol", label="Symbol", kind="tag"),
                ColumnSpec(key="title", label="Title", kind="text"),
                ColumnSpec(key="media_type", label="Type", kind="tag"),
                ColumnSpec(key="duration_seconds", label="Length", kind="duration"),
                ColumnSpec(key="source", label="Source", kind="tag"),
                ColumnSpec(key="has_transcript", label="Transcript", kind="tag"),
                ColumnSpec(key="play", label="Play", kind="action"),
            ],
            sortable=True,
            filterable=True,
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="total_items", label="Items", kind="kpi"),
                CardSlot(key="items_with_transcript", label="With Transcript", kind="kpi"),
                CardSlot(key="latest_event_date", label="Latest", kind="timestamp"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "AV is backed by the internal media archive (engine/services/media_archive). Each row "
            "is a real, playable resource: the `play_url` is a verifiable HTTPS link to the "
            "source audio/video (earnings call replay, Fed presser, conference recording, "
            "podcast episode); `duration_seconds` is read from the asset's manifest, not "
            "estimated; `has_transcript` is true only when a stored transcript exists in the "
            "transcripts_archive (and TRAN can render it). The archive is a playable archive, "
            "not a placeholder list — empty filter results return items=[] with a warning "
            "explaining 'no archive entries for these filters', never a synthetic 'coming soon' "
            "row. When the underlying archive directory is missing, data_mode reports "
            "'not_configured' and items=[] with a setup-hint warning."
        ),
        field_dict={
            "items[].event_date": FieldDef(unit="iso8601", description="Recording timestamp in UTC.", source="archive"),
            "items[].symbol": FieldDef(description="Primary ticker tag (optional for macro/podcasts).", source="archive"),
            "items[].title": FieldDef(description="Display title.", source="archive"),
            "items[].media_type": FieldDef(description="earnings_call / central_bank_presser / conference / podcast / interview.", source="archive"),
            "items[].duration_seconds": FieldDef(unit="seconds", description="Asset duration read from the manifest.", source="archive"),
            "items[].play_url": FieldDef(unit="url", description="Verifiable HTTPS link to play the asset.", source="archive"),
            "items[].source": FieldDef(description="Source publisher (e.g. ir.apple.com, federalreserve.gov).", source="archive"),
            "items[].has_transcript": FieldDef(description="True when a stored transcript exists for the item.", source="derived"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="av_items_have_real_play_url",
                description="Asserts every item has a non-empty play_url and the URL scheme is http(s) — playable archive, not placeholder list.",
                inputs={},
                assertions=[
                    "every_item_has_play_url",
                    "every_play_url_is_http_or_https",
                ],
            ),
            SemanticTest(
                name="av_empty_filter_returns_empty_items_not_placeholder",
                description="When the filters yield no archive entries, asserts items=[] and a warning explains 'no archive entries'; no synthetic placeholder row appears.",
                inputs={"symbol": "ZZZZ", "_mock": "archive_empty"},
                assertions=[
                    "items_is_empty_array",
                    "warning_mentions_no_archive_entries",
                    "no_synthetic_placeholder_row",
                ],
            ),
            SemanticTest(
                name="av_duration_is_real_not_estimated",
                description="Asserts duration_seconds is read from the asset manifest (integer seconds) and is not a default zero.",
                inputs={},
                assertions=["duration_seconds_is_positive_integer"],
            ),
            SemanticTest(
                name="av_has_transcript_matches_archive",
                description="When a transcript exists in transcripts_archive for the item, asserts has_transcript == true; otherwise false.",
                inputs={},
                assertions=["has_transcript_matches_transcripts_archive"],
            ),
        ],
    )


__all__ = ["av"]
