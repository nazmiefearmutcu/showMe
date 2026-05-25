"""SAT — Satellite imagery (commodity intel).

SAT pulls geo-tagged satellite imagery (Sentinel-2 etc.) for a target
AOI to support commodity intel (oil storage, port congestion, crop
health, refinery activity). Without a SentinelHub / Planet credential
configured, SAT declares NOT_CONFIGURED and renders an explicit
unavailable card — it shows real imagery or explicit unavailable,
never pretends with synthetic tiles.
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
def sat() -> FunctionManifest:
    return FunctionManifest(
        code="SAT",
        name="Satellite Imagery",
        category=Category.MISC,
        intent=(
            "Surface geo-tagged satellite imagery (Sentinel-2 etc.) for commodity intel "
            "(oil storage, port congestion, crop health, refinery activity); declares "
            "unavailable when no SentinelHub / Planet credential is configured."
        ),
        asset_classes=[AssetClass.COMMODITY],
        inputs=[
            InputSpec(
                name="aoi",
                label="Area of Interest",
                control=ControlKind.SELECT,
                required=True,
                description="Curated AOI preset (Cushing tank farm, Singapore strait, etc.).",
                options=[
                    "cushing_ok",
                    "singapore_strait",
                    "shanghai_port",
                    "rotterdam_port",
                    "saudi_ras_tanura",
                    "iowa_corn_belt",
                ],
            ),
            InputSpec(
                name="layer",
                label="Layer",
                control=ControlKind.SELECT,
                required=True,
                description="Sentinel-2 visualisation layer.",
                options=["true_color", "ndvi", "moisture", "thermal", "swir"],
            ),
            InputSpec(
                name="capture_date",
                label="Capture date",
                control=ControlKind.DATE_RANGE,
                required=False,
                description="Target capture date or short window; defaults to latest available.",
            ),
        ],
        defaults={
            "aoi": "cushing_ok",
            "layer": "true_color",
        },
        provider_chain=ProviderChain(
            primary="internal",
            fallbacks=[],
            acceptable_modes=[
                DataMode.NOT_CONFIGURED,
                DataMode.CACHED_SNAPSHOT,
            ],
        ),
        caching=CachingPolicy(ttl_seconds=3600, scope="per_input", persist=True),
        output_contract=OutputContract(
            must_have=["data_mode"],
            rows=True,
            series=False,
            cards=True,
            warnings=True,
            next_actions=True,
        ),
        table_schema=TableSchema(
            columns=[
                ColumnSpec(key="capture_utc", label="Captured", kind="datetime", format="yyyy-MM-dd"),
                ColumnSpec(key="aoi", label="AOI", kind="tag"),
                ColumnSpec(key="layer", label="Layer", kind="tag"),
                ColumnSpec(key="cloud_pct", label="Cloud", kind="percent", format="%.1f"),
                ColumnSpec(key="tile_url", label="Tile", kind="action"),
                ColumnSpec(key="source", label="Source", kind="tag"),
            ],
        ),
        card_schema=CardSchema(
            slots=[
                CardSlot(key="aoi", label="AOI", kind="badge"),
                CardSlot(key="latest_capture", label="Latest capture", kind="timestamp"),
                CardSlot(key="cloud_pct", label="Cloud cover", kind="kpi", unit="%"),
                CardSlot(key="data_mode", label="Mode", kind="mode_pill"),
                CardSlot(key="as_of", label="As of", kind="timestamp"),
            ],
        ),
        methodology=(
            "SAT shows real imagery or explicit unavailable, never pretends. The handler "
            "requires a SentinelHub / Planet credential in the keyring; with no key configured "
            "it returns data_mode='not_configured' with rows=[] and a card-level notice — no "
            "synthetic tiles, no placeholder thumbnails, no fabricated cloud percentages. "
            "When a key is present, the chain queries the configured catalog for the AOI + "
            "layer + capture_date window, picks the lowest-cloud match, and returns the tile "
            "URL plus capture metadata. Cached snapshots survive across launches because tile "
            "imagery is bandwidth-heavy."
        ),
        field_dict={
            "data_mode": FieldDef(description="not_configured | cached_snapshot | delayed_reference.", source="envelope"),
            "rows[].capture_utc": FieldDef(unit="UTC", description="Image capture time.", source="provider"),
            "rows[].cloud_pct": FieldDef(unit="%", description="Cloud coverage percentage at capture.", source="provider"),
            "rows[].tile_url": FieldDef(description="Provider tile URL for the requested layer.", source="provider"),
        },
        provenance=ProvenanceSpec(
            require_source_list=True,
            require_as_of=True,
            require_latency_ms=True,
        ),
        alerting=None,
        semantic_tests=[
            SemanticTest(
                name="sat_explicit_unavailable_when_not_configured",
                description="With no SentinelHub / Planet credential, SAT returns data_mode='not_configured', rows=[], and a warning naming the missing credential — never a synthetic tile.",
                inputs={"_env": "no_sentinelhub_key"},
                assertions=[
                    "data_mode_equals_not_configured",
                    "rows_is_empty_array",
                    "warning_mentions_not_configured",
                    "no_synthetic_tiles",
                ],
            ),
            SemanticTest(
                name="sat_real_imagery_or_explicit_unavailable_never_placeholder",
                description="Every returned row must carry a real tile_url and a numeric cloud_pct — placeholder tiles or null cloud values are rejected.",
                inputs={"aoi": "cushing_ok"},
                assertions=[
                    "tile_url_is_real_url",
                    "cloud_pct_is_numeric",
                    "no_placeholder_thumbnail",
                ],
            ),
            SemanticTest(
                name="sat_picks_lowest_cloud_within_window",
                description="When multiple captures exist inside the requested window, SAT returns the row with the lowest cloud_pct.",
                inputs={"aoi": "cushing_ok", "capture_date": "last_7d"},
                assertions=["selected_row_has_min_cloud_pct_in_window"],
            ),
        ],
    )


__all__ = ["sat"]
