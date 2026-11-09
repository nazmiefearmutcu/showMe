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
                description="Filter by media kind: filing (SEC filing document) or podcast (RSS audio episode); empty = all.",
                options=["filing", "podcast"],
            ),
            InputSpec(
                name="date_range",
                label="Date range",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Restrict to items in this window: last_Nd (e.g. last_30d, last_365d) or all; empty = last_90d.",
            ),
        ],
        defaults={
            "symbol": "",
            "media_type": [],
            "date_range": "last_90d",
        },
        provider_chain=ProviderChain(
            primary="sec_edgar",
            fallbacks=[],
            acceptable_modes=[
                DataMode.LIVE_OFFICIAL,
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
            "AV is a playable archive built from two keyless public sources. With a symbol, the "
            "default path reads the issuer's recent SEC EDGAR submissions "
            "(data.sec.gov/submissions, descriptive User-Agent) and returns its investor-relevant "
            "filings (8-K, 10-Q, 10-K, 6-K, 20-F, ARS, DEF 14A) as filing rows; event_date is the "
            "SEC filing date and play_url is the HTTPS filing document. Without a symbol (global "
            "scope) it reads public finance podcast RSS feeds (NPR Planet Money, The Indicator, "
            "Up First, a finance interview feed) and returns real audio episodes whose play_url is "
            "the enclosure URL and duration_seconds comes from the feed's itunes:duration. The "
            "date_range window (default last_90d) is applied to every row. No transcript store is "
            "wired, so has_transcript is always false. The archive is not a placeholder list: empty "
            "filter results return rows=[] with an explanatory reason, and a window with no matches "
            "returns status='empty', while a genuine network outage returns "
            "status='provider_unavailable' with next_actions."
        ),
        field_dict={
            "items[].event_date": FieldDef(unit="iso8601", description="SEC filing date (filings) or episode publish date (podcasts).", source="archive"),
            "items[].period_end": FieldDef(unit="iso8601", description="SEC fiscal period end (filings only).", source="archive"),
            "items[].symbol": FieldDef(description="Primary ticker tag (filings only; empty for podcasts).", source="archive"),
            "items[].title": FieldDef(description="Display title.", source="archive"),
            "items[].media_type": FieldDef(description="filing (SEC filing document) or podcast (RSS audio episode).", source="archive"),
            "items[].duration_seconds": FieldDef(unit="seconds", description="Episode duration from the RSS itunes:duration; null for filings.", source="archive"),
            "items[].play_url": FieldDef(unit="url", description="Verifiable HTTPS link: SEC filing document or audio enclosure.", source="archive"),
            "items[].source": FieldDef(description="Source publisher (sec.gov or the podcast feed title).", source="archive"),
            "items[].has_transcript": FieldDef(description="Always false: no stored transcript provider is wired.", source="derived"),
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
                description="Asserts duration_seconds comes from the RSS itunes:duration (integer seconds) and is null for filings, never a default zero.",
                inputs={},
                assertions=["duration_seconds_is_positive_integer"],
            ),
            SemanticTest(
                name="av_has_transcript_is_false_without_store",
                description="No transcript store is wired, so has_transcript is false on every item.",
                inputs={},
                assertions=["has_transcript_is_false"],
            ),
        ],
    )


__all__ = ["av"]
